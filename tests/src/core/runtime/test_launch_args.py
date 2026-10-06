"""Tests for launch-only runtime arguments (effort + `--` passthrough)."""

from __future__ import annotations

import pytest

from forge.core.effort import CLAUDE_EFFORT_LEVELS, CODEX_EFFORT_LEVELS
from forge.core.runtime.launch_args import (
    ALL_EFFORT_LEVELS,
    LaunchArgsError,
    LaunchRuntime,
    RuntimeLaunchArgs,
    validate_launch_args,
)


class TestEffortVocabulary:
    def test_all_levels_is_the_ordered_union(self) -> None:
        assert ALL_EFFORT_LEVELS == ("none", "minimal", "low", "medium", "high", "xhigh", "max")
        assert set(ALL_EFFORT_LEVELS) == set(CLAUDE_EFFORT_LEVELS) | set(CODEX_EFFORT_LEVELS)

    @pytest.mark.parametrize("level", CLAUDE_EFFORT_LEVELS)
    def test_claude_accepts_its_levels(self, level: str) -> None:
        args = RuntimeLaunchArgs(effort=level)
        assert validate_launch_args(args, runtime="claude_code", advisory=False) is args

    @pytest.mark.parametrize("level", ["none", "minimal"])
    def test_claude_rejects_codex_only_levels(self, level: str) -> None:
        with pytest.raises(LaunchArgsError, match="--effort for Claude sessions must be one of low, medium"):
            validate_launch_args(RuntimeLaunchArgs(effort=level), runtime="claude_code", advisory=False)

    @pytest.mark.parametrize("level", CODEX_EFFORT_LEVELS)
    def test_codex_accepts_openai_union(self, level: str) -> None:
        validate_launch_args(RuntimeLaunchArgs(effort=level), runtime="codex", advisory=False)

    def test_codex_rejects_unknown_level(self) -> None:
        with pytest.raises(LaunchArgsError, match="--effort for Codex sessions"):
            validate_launch_args(RuntimeLaunchArgs(effort="ultra"), runtime="codex", advisory=False)


class TestArgvProjection:
    def test_empty_args_add_nothing(self) -> None:
        assert RuntimeLaunchArgs().runtime_argv("claude_code") == []
        assert RuntimeLaunchArgs().runtime_argv("codex") == []

    def test_claude_effort_precedes_passthrough(self) -> None:
        args = RuntimeLaunchArgs(effort="high", passthrough=("--debug", "api"))
        assert args.runtime_argv("claude_code") == ["--effort", "high", "--debug", "api"]

    def test_codex_effort_is_a_quoted_config_override(self) -> None:
        args = RuntimeLaunchArgs(effort="xhigh", passthrough=("-m", "gpt-5.3-codex"))
        assert args.runtime_argv("codex") == ["-c", 'model_reasoning_effort="xhigh"', "-m", "gpt-5.3-codex"]

    def test_recovery_argv_separates_options_from_passthrough(self) -> None:
        args = RuntimeLaunchArgs(effort="low", passthrough=("--verbose",))
        assert args.recovery_argv() == (("--effort", "low"), ("--verbose",))
        assert RuntimeLaunchArgs().recovery_argv() == ((), ())


class TestClaudeReservedFlags:
    @pytest.mark.parametrize(
        "token",
        [
            "--session-id",
            "--session-id=abc",
            "-r",
            "-rabc",
            "--resume",
            "--resume=abc",
            "-c",
            "--continue",
            "--from-pr",
            "--fork-session",
            "-w",
            "-wother",
            "--worktree",
            "--worktree=other",
            "-n",
            "--name=x",
            "--model",
            "--model=opus",
            "--effort",
            "--append-system-prompt-file",
            "-p",
            "--print",
            "--bare",
        ],
    )
    def test_reserved_spellings_rejected(self, token: str) -> None:
        with pytest.raises(LaunchArgsError, match="is managed by Forge"):
            validate_launch_args(RuntimeLaunchArgs(passthrough=(token,)), runtime="claude_code", advisory=False)

    def test_rejection_names_the_flag_without_its_value(self) -> None:
        with pytest.raises(LaunchArgsError, match=r"Claude flag '--model' is managed by Forge: use Forge '--model'"):
            validate_launch_args(
                RuntimeLaunchArgs(passthrough=("--model=opus",)), runtime="claude_code", advisory=False
            )

    @pytest.mark.parametrize(
        "passthrough",
        [
            ("--debug",),
            ("--verbose", "--add-dir", "/tmp/x"),
            ("--permission-mode", "plan"),
            ("--append-system-prompt", "be brief"),
            ("--dangerously-skip-permissions",),
            # Similar-looking long flags are not prefix matches of reserved ones.
            ("--resume-like-flag",),
            ("--models-cache",),
        ],
    )
    def test_unmanaged_flags_pass_through(self, passthrough: tuple[str, ...]) -> None:
        args = RuntimeLaunchArgs(passthrough=passthrough)
        assert validate_launch_args(args, runtime="claude_code", advisory=False) is args


class TestCodexReservedFlags:
    @pytest.mark.parametrize(
        "token",
        [
            "-s",
            "--sandbox",
            "--sandbox=read-only",
            "-C",
            "--cd",
            "-p",
            "--profile",
            "--worktree",
            "--worktree=other",
            "--oss",
            "--local-provider",
            "--local-provider=ollama",
            "--remote",
            "--remote=ws://localhost:9876",
            "--remote-auth-token-env",
            "--remote-auth-token-env=REMOTE_TOKEN",
            "--ephemeral",
            "--json",
            "--dangerously-bypass-hook-trust",
            "--dangerously-bypass-approvals-and-sandbox",
            "--yolo",
        ],
    )
    def test_reserved_spellings_rejected(self, token: str) -> None:
        with pytest.raises(LaunchArgsError, match="Codex flag .* is managed by Forge"):
            validate_launch_args(RuntimeLaunchArgs(passthrough=(token,)), runtime="codex", advisory=False)

    @pytest.mark.parametrize(
        "passthrough",
        [
            ("-c", "model_reasoning_effort=high"),
            ("--config", "model_reasoning_effort=high"),
            ("--config=model_reasoning_effort=high",),
            ("-cmodel_reasoning_effort=high",),
            ("-c", "model_provider=custom"),
            ("-c", "model_providers.custom.base_url=http://x"),
        ],
    )
    def test_reserved_config_keys_rejected(self, passthrough: tuple[str, ...]) -> None:
        with pytest.raises(LaunchArgsError, match="Codex config override .* is managed by Forge"):
            validate_launch_args(RuntimeLaunchArgs(passthrough=passthrough), runtime="codex", advisory=False)

    @pytest.mark.parametrize(
        "passthrough",
        [
            # Codex model choice is runtime-owned; Forge neither pins nor records it.
            ("-m", "gpt-5.3-codex"),
            ("-c", "model_verbosity=low"),
            ("--enable", "web_search"),
            ("--skip-git-repo-check",),
        ],
    )
    def test_unmanaged_flags_pass_through(self, passthrough: tuple[str, ...]) -> None:
        validate_launch_args(RuntimeLaunchArgs(passthrough=passthrough), runtime="codex", advisory=False)

    def test_claude_only_short_flag_is_not_reserved_for_codex(self) -> None:
        # Codex `-c` is a config override, not Claude's `--continue`.
        validate_launch_args(RuntimeLaunchArgs(passthrough=("-c", "x=1")), runtime="codex", advisory=False)


class TestAdvisoryRefusal:
    @pytest.mark.parametrize("runtime", ["claude_code", "codex"])
    def test_any_passthrough_refused(self, runtime: LaunchRuntime) -> None:
        with pytest.raises(LaunchArgsError, match="not accepted for advisory-authority launches"):
            validate_launch_args(
                RuntimeLaunchArgs(passthrough=("--verbose",)),
                runtime=runtime,
                advisory=True,
            )

    @pytest.mark.parametrize("runtime", ["claude_code", "codex"])
    def test_effort_alone_is_allowed(self, runtime: LaunchRuntime) -> None:
        validate_launch_args(
            RuntimeLaunchArgs(effort="high"),
            runtime=runtime,
            advisory=True,
        )
