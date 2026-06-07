"""Tests for forge.core.reactive.env."""

from __future__ import annotations

from unittest.mock import patch

from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_MAX_DEPTH,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    InteractiveApiKeyDecision,
    RunIdentity,
    apply_interactive_api_key,
    build_claude_env,
    can_use_bare,
    compute_interactive_api_key_decision,
    derive_child_run_identity,
    get_forge_depth,
    get_run_identity,
    mint_run_id,
    new_root_run_identity,
    should_spawn_subprocesses,
)


class TestBuildClaudeEnv:
    def test_returns_copy_of_environ(self):
        """Returned dict should not mutate os.environ."""
        env = build_claude_env()
        env["__TEST_KEY__"] = "should_not_leak"
        import os

        assert "__TEST_KEY__" not in os.environ

    def test_sets_anthropic_base_url(self):
        env = build_claude_env(base_url="http://localhost:8085")
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:8085"

    def test_no_base_url_preserves_existing(self):
        """When base_url is None, ANTHROPIC_BASE_URL is not injected."""
        with patch.dict("os.environ", {}, clear=True):
            env = build_claude_env()
        assert "ANTHROPIC_BASE_URL" not in env

    def test_extra_vars_override(self):
        env = build_claude_env(extra_vars={"HOME": "/custom", "FOO": "bar"})
        assert env["HOME"] == "/custom"
        assert env["FOO"] == "bar"

    def test_base_url_takes_precedence_over_extra_vars(self):
        """Explicit base_url wins over extra_vars for ANTHROPIC_BASE_URL."""
        env = build_claude_env(
            base_url="http://from-base-url",
            extra_vars={"ANTHROPIC_BASE_URL": "http://from-extra"},
        )
        assert env["ANTHROPIC_BASE_URL"] == "http://from-base-url"

    def test_increments_forge_depth_from_zero(self):
        """Child env gets FORGE_DEPTH=1 when parent has no depth set."""
        with patch.dict("os.environ", {}, clear=True):
            env = build_claude_env()
        assert env[FORGE_DEPTH_VAR] == "1"

    def test_increments_forge_depth_from_existing(self):
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "1"}, clear=True):
            env = build_claude_env()
        assert env[FORGE_DEPTH_VAR] == "2"

    def test_increments_forge_depth_from_zero_string(self):
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "0"}, clear=True):
            env = build_claude_env()
        assert env[FORGE_DEPTH_VAR] == "1"

    def test_increments_forge_depth_invalid_treated_as_zero(self):
        """Invalid FORGE_DEPTH → treated as 0, child gets 1."""
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "abc"}, clear=True):
            env = build_claude_env()
        assert env[FORGE_DEPTH_VAR] == "1"

    def test_extra_vars_forge_depth_is_incremented(self):
        """extra_vars participate in depth calculation but cannot bypass the child increment."""
        env = build_claude_env(extra_vars={FORGE_DEPTH_VAR: "99"})
        assert env[FORGE_DEPTH_VAR] == "100"

    def test_direct_unsets_inherited_proxy_url(self):
        """direct=True removes inherited ANTHROPIC_BASE_URL from parent env."""
        with patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "http://proxy:8085"}):
            env = build_claude_env(direct=True)
        assert "ANTHROPIC_BASE_URL" not in env

    def test_direct_without_inherited_url_is_safe(self):
        """direct=True is a no-op when parent has no ANTHROPIC_BASE_URL."""
        with patch.dict("os.environ", {}, clear=True):
            env = build_claude_env(direct=True)
        assert "ANTHROPIC_BASE_URL" not in env

    def test_base_url_takes_precedence_over_direct(self):
        """Explicit base_url wins over direct flag."""
        with patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "http://old:8085"}):
            env = build_claude_env(base_url="http://new:8086", direct=True)
        assert env["ANTHROPIC_BASE_URL"] == "http://new:8086"


class TestGetForgeDepth:
    def test_unset_returns_zero(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_forge_depth() == 0

    def test_reads_numeric_value(self):
        assert get_forge_depth({FORGE_DEPTH_VAR: "2"}) == 2

    def test_reads_zero(self):
        assert get_forge_depth({FORGE_DEPTH_VAR: "0"}) == 0

    def test_invalid_string_returns_zero(self):
        assert get_forge_depth({FORGE_DEPTH_VAR: "abc"}) == 0

    def test_negative_clamped_to_zero(self):
        assert get_forge_depth({FORGE_DEPTH_VAR: "-1"}) == 0

    def test_empty_string_returns_zero(self):
        assert get_forge_depth({FORGE_DEPTH_VAR: ""}) == 0

    def test_reads_from_os_environ_by_default(self):
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "3"}):
            assert get_forge_depth() == 3

    def test_explicit_env_overrides_os_environ(self):
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "5"}):
            assert get_forge_depth({FORGE_DEPTH_VAR: "2"}) == 2


class TestShouldSpawnSubprocesses:
    def test_true_at_depth_zero(self):
        assert should_spawn_subprocesses({}) is True

    def test_true_at_depth_one(self):
        assert should_spawn_subprocesses({FORGE_DEPTH_VAR: "1"}) is True

    def test_false_at_max_depth(self):
        assert should_spawn_subprocesses({FORGE_DEPTH_VAR: str(FORGE_MAX_DEPTH)}) is False

    def test_false_above_max_depth(self):
        assert should_spawn_subprocesses({FORGE_DEPTH_VAR: str(FORGE_MAX_DEPTH + 1)}) is False

    def test_reads_from_os_environ_by_default(self):
        with patch.dict("os.environ", {FORGE_DEPTH_VAR: str(FORGE_MAX_DEPTH)}):
            assert should_spawn_subprocesses() is False

    def test_invalid_value_allows_spawn(self):
        """Invalid depth → 0 → allow spawn (fail-open)."""
        assert should_spawn_subprocesses({FORGE_DEPTH_VAR: "garbage"}) is True


class TestCanUseBare:
    def test_true_when_api_key_present(self):
        assert can_use_bare({"ANTHROPIC_API_KEY": "sk-test"}) is True

    def test_false_when_api_key_absent(self):
        assert can_use_bare({}) is False

    def test_false_when_api_key_empty(self):
        assert can_use_bare({"ANTHROPIC_API_KEY": ""}) is False

    def test_reads_from_os_environ_by_default(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            assert can_use_bare() is True

    def test_reads_from_os_environ_absent(self):
        with patch.dict("os.environ", {}, clear=True):
            assert can_use_bare() is False


class TestCredentialHydration:
    """build_claude_env injects resolved credentials into the subprocess env."""

    def test_file_key_injected_when_env_absent(self, monkeypatch):
        """Credential-file key appears in built env even when not in os.environ."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "forge.core.reactive.env._hydrate_credentials",
            lambda env: env.__setitem__("ANTHROPIC_API_KEY", "from-file"),
        )
        env = build_claude_env()
        assert env["ANTHROPIC_API_KEY"] == "from-file"

    def test_can_use_bare_on_hydrated_env(self, monkeypatch):
        """can_use_bare(env) sees the hydrated key after build_claude_env."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "forge.core.reactive.env._hydrate_credentials",
            lambda env: env.__setitem__("ANTHROPIC_API_KEY", "from-file"),
        )
        env = build_claude_env()
        assert can_use_bare(env) is True

    def test_ignore_env_scrubs_and_replaces(self, monkeypatch):
        """With auth_ignore_env, env value is replaced by credential-file value."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-ignored")

        def mock_hydrate(env):
            env["ANTHROPIC_API_KEY"] = "file-key"

        monkeypatch.setattr("forge.core.reactive.env._hydrate_credentials", mock_hydrate)
        env = build_claude_env()
        assert env["ANTHROPIC_API_KEY"] == "file-key"

    def test_ignore_env_removes_when_no_file_value(self, monkeypatch):
        """With auth_ignore_env and no file value, key is removed from env."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-ignored")

        def mock_hydrate(env):
            env.pop("ANTHROPIC_API_KEY", None)

        monkeypatch.setattr("forge.core.reactive.env._hydrate_credentials", mock_hydrate)
        env = build_claude_env()
        assert "ANTHROPIC_API_KEY" not in env


class TestHydrateCredentialsIntegration:
    """Integration tests for _hydrate_credentials with real resolve logic."""

    def test_no_op_when_env_has_key_and_ignore_off(self, monkeypatch):
        """When env has the key and ignore is off, no change."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        monkeypatch.setattr(
            "forge.core.reactive.env._hydrate_credentials.__module__",
            "forge.core.reactive.env",
        )
        env = build_claude_env()
        assert env["ANTHROPIC_API_KEY"] == "env-key"

    def test_file_fallback_when_env_missing(self, monkeypatch):
        """When env key is absent, credential file value is injected."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda var: "file-key" if var == "ANTHROPIC_API_KEY" else None,
        )
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._auth_ignore_env",
            lambda: False,
        )
        env = build_claude_env()
        assert env.get("ANTHROPIC_API_KEY") == "file-key"

    def test_ignore_env_overrides_env_key(self, monkeypatch):
        """When auth_ignore_env is active, env key is replaced by file key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        # Patch both resolution paths that _hydrate_credentials uses:
        # 1. resolve_env_or_credential (respects auth_ignore_env via template_secrets)
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._auth_ignore_env",
            lambda: True,
        )
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._get_file_secrets",
            lambda: {"ANTHROPIC_API_KEY": "file-key"},
        )
        # 2. The runtime config check inside _hydrate_credentials
        monkeypatch.setattr(
            "forge.runtime_config.get_runtime_config",
            lambda: type("C", (), {"auth_ignore_env": True})(),
        )
        env = build_claude_env()
        assert env["ANTHROPIC_API_KEY"] == "file-key"

    def test_ignore_env_removes_env_key_when_file_missing(self, monkeypatch):
        """When auth_ignore_env is active and file has no key, inherited env key is scrubbed."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._auth_ignore_env",
            lambda: True,
        )
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._get_file_secrets",
            lambda: {},
        )
        monkeypatch.setattr(
            "forge.runtime_config.get_runtime_config",
            lambda: type("C", (), {"auth_ignore_env": True})(),
        )

        env = build_claude_env()

        assert "ANTHROPIC_API_KEY" not in env


def _cfg(*, omit: bool = False, ignore_env: bool = False):
    """Runtime-config stub exposing the two fields the api-key logic reads."""
    return type(
        "C",
        (),
        {
            "interactive_anthropic_api_key": "omit" if omit else "inherit",
            "auth_ignore_env": ignore_env,
        },
    )()


class TestInteractiveApiKey:
    """compute/apply for ANTHROPIC_API_KEY on interactive launches (G4)."""

    def test_omit_strips_key_for_interactive(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell")
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg(omit=True))
        env = {"ANTHROPIC_API_KEY": "sk-shell"}
        decision = apply_interactive_api_key(env, interactive=True)
        assert "ANTHROPIC_API_KEY" not in env
        assert decision == InteractiveApiKeyDecision(available=False, source="omitted_by_config")

    def test_omit_is_ignored_for_headless(self, monkeypatch):
        # interactive=False must never honor omit: headless subprocesses keep auth.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell")
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg(omit=True))
        env: dict[str, str] = {}
        decision = apply_interactive_api_key(env, interactive=False)
        assert env["ANTHROPIC_API_KEY"] == "sk-shell"
        assert decision == InteractiveApiKeyDecision(available=True, source="env")

    def test_inherit_keeps_env_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell")
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg())
        env: dict[str, str] = {}
        decision = apply_interactive_api_key(env, interactive=True)
        assert env["ANTHROPIC_API_KEY"] == "sk-shell"
        assert decision == InteractiveApiKeyDecision(available=True, source="env")

    def test_inherit_file_fallback(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg())
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._get_file_secrets",
            lambda: {"ANTHROPIC_API_KEY": "sk-file"},
        )
        env: dict[str, str] = {}
        decision = apply_interactive_api_key(env, interactive=True)
        assert env["ANTHROPIC_API_KEY"] == "sk-file"
        assert decision == InteractiveApiKeyDecision(available=True, source="credential_file")

    def test_auth_ignore_env_reports_credential_file_source(self, monkeypatch):
        # The correctness trap: with auth_ignore_env the child uses the FILE key
        # even though a shell key exists, so the recorded source must be
        # credential_file, not env.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell")
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg(ignore_env=True))
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._get_file_secrets",
            lambda: {"ANTHROPIC_API_KEY": "sk-file"},
        )
        env: dict[str, str] = {}
        decision = apply_interactive_api_key(env, interactive=True)
        assert env["ANTHROPIC_API_KEY"] == "sk-file"
        assert decision.source == "credential_file"

    def test_inherit_no_key_anywhere(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg())
        monkeypatch.setattr("forge.core.auth.template_secrets._get_file_secrets", lambda: {})
        env = {"ANTHROPIC_API_KEY": "stale"}
        decision = apply_interactive_api_key(env, interactive=True)
        assert "ANTHROPIC_API_KEY" not in env  # authoritative: pops a stale value
        assert decision == InteractiveApiKeyDecision(available=False, source="none")

    def test_apply_is_authoritative_over_extra_vars(self, monkeypatch):
        # A stale key injected via extra_vars must not survive omit.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg(omit=True))
        env = {"ANTHROPIC_API_KEY": "sk-from-extra-vars"}
        apply_interactive_api_key(env, interactive=True)
        assert "ANTHROPIC_API_KEY" not in env

    def test_compute_matches_apply(self, monkeypatch):
        # The recorder uses compute; the env build uses apply. Same inputs -> same decision.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-shell")
        monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _cfg(omit=True))
        computed = compute_interactive_api_key_decision(interactive=True)
        applied = apply_interactive_api_key({}, interactive=True)
        assert computed == applied


class TestRunIdentityHelpers:
    def test_mint_run_id_format(self):
        rid = mint_run_id()
        assert rid.startswith("run_")
        assert len(rid) == len("run_") + 12

    def test_mint_run_id_unique(self):
        assert mint_run_id() != mint_run_id()

    def test_new_root_has_no_parent_and_is_own_root(self):
        root = new_root_run_identity()
        assert root.parent_run_id is None
        assert root.run_id == root.root_run_id

    def test_get_run_identity_none_when_unset(self):
        assert get_run_identity({}) is None

    def test_get_run_identity_reads_env(self):
        rid = get_run_identity(
            {
                FORGE_RUN_ID_VAR: "run_self",
                FORGE_PARENT_RUN_ID_VAR: "run_parent",
                FORGE_ROOT_RUN_ID_VAR: "run_root",
            }
        )
        assert rid == RunIdentity(run_id="run_self", parent_run_id="run_parent", root_run_id="run_root")

    def test_get_run_identity_root_falls_back_to_run_id(self):
        rid = get_run_identity({FORGE_RUN_ID_VAR: "run_self"})
        assert rid is not None
        assert rid.root_run_id == "run_self"
        assert rid.parent_run_id is None

    def test_derive_child_inherits_root_parent_is_spawner(self):
        child = derive_child_run_identity({FORGE_RUN_ID_VAR: "run_spawn", FORGE_ROOT_RUN_ID_VAR: "run_root"})
        assert child.parent_run_id == "run_spawn"
        assert child.root_run_id == "run_root"
        assert child.run_id not in ("run_spawn", "run_root")

    def test_derive_child_of_nothing_is_fresh_root(self):
        child = derive_child_run_identity({})
        assert child.parent_run_id is None
        assert child.run_id == child.root_run_id

    def test_derive_child_ignores_stale_parent(self):
        # A stale inherited FORGE_PARENT_RUN_ID must not become the child's parent;
        # parent is always recomputed from the spawner's FORGE_RUN_ID.
        child = derive_child_run_identity(
            {
                FORGE_RUN_ID_VAR: "run_spawn",
                FORGE_PARENT_RUN_ID_VAR: "run_stale",
                FORGE_ROOT_RUN_ID_VAR: "run_root",
            }
        )
        assert child.parent_run_id == "run_spawn"

    def test_as_env_root_omits_parent(self):
        env = new_root_run_identity().as_env()
        assert FORGE_PARENT_RUN_ID_VAR not in env
        assert env[FORGE_RUN_ID_VAR] == env[FORGE_ROOT_RUN_ID_VAR]

    def test_as_env_child_includes_parent(self):
        env = RunIdentity(run_id="run_c", parent_run_id="run_p", root_run_id="run_r").as_env()
        assert env[FORGE_PARENT_RUN_ID_VAR] == "run_p"


class TestBuildClaudeEnvRunIdentity:
    def test_mints_root_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_claude_env()
        assert env[FORGE_RUN_ID_VAR].startswith("run_")
        assert env[FORGE_RUN_ID_VAR] == env[FORGE_ROOT_RUN_ID_VAR]
        assert FORGE_PARENT_RUN_ID_VAR not in env

    def test_child_inherits_root_parent_is_spawner(self):
        with patch.dict(
            "os.environ",
            {FORGE_RUN_ID_VAR: "run_spawn", FORGE_ROOT_RUN_ID_VAR: "run_root"},
            clear=True,
        ):
            env = build_claude_env()
        assert env[FORGE_PARENT_RUN_ID_VAR] == "run_spawn"
        assert env[FORGE_ROOT_RUN_ID_VAR] == "run_root"
        assert env[FORGE_RUN_ID_VAR] not in ("run_spawn", "run_root")

    def test_derive_run_identity_false_passes_through(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_claude_env(
                extra_vars={FORGE_RUN_ID_VAR: "run_fixed", FORGE_ROOT_RUN_ID_VAR: "run_fixed"},
                derive_run_identity=False,
            )
        assert env[FORGE_RUN_ID_VAR] == "run_fixed"
        assert env[FORGE_ROOT_RUN_ID_VAR] == "run_fixed"

    def test_stale_parent_scrubbed_on_derive(self):
        # Inherited FORGE_PARENT_RUN_ID (the spawner's own parent) must not leak.
        with patch.dict(
            "os.environ",
            {
                FORGE_RUN_ID_VAR: "run_spawn",
                FORGE_PARENT_RUN_ID_VAR: "run_stale",
                FORGE_ROOT_RUN_ID_VAR: "run_root",
            },
            clear=True,
        ):
            env = build_claude_env()
        assert env[FORGE_PARENT_RUN_ID_VAR] == "run_spawn"

    def test_source_env_not_mutated(self):
        import os

        with patch.dict("os.environ", {FORGE_DEPTH_VAR: "1", FORGE_RUN_ID_VAR: "run_src"}, clear=True):
            env = build_claude_env()
            # Child env advances depth and gets a fresh run id...
            assert env[FORGE_DEPTH_VAR] == "2"
            assert env[FORGE_RUN_ID_VAR] != "run_src"
            # ...while the source os.environ is untouched.
            assert os.environ[FORGE_DEPTH_VAR] == "1"
            assert os.environ[FORGE_RUN_ID_VAR] == "run_src"
