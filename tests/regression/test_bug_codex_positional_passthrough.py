"""Codex passthrough must not replace Forge's subcommand, thread id, or prompt."""

import pytest

from forge.core.runtime.launch_args import (
    LaunchArgsError,
    RuntimeLaunchArgs,
    validate_launch_args,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "tokens",
    [
        ("resume", "other-thread"),
        ("fork", "other-thread"),
        ("other-thread",),
        ("--skip-git-repo-check", "resume", "other-thread"),
        ("--", "other-thread"),
        ("--model", "gpt-5.5", "other-thread"),
        ("--model",),
        ("--model", "--search"),
    ],
)
def test_codex_tail_cannot_change_managed_lifecycle(tokens: tuple[str, ...]) -> None:
    with pytest.raises(LaunchArgsError):
        validate_launch_args(RuntimeLaunchArgs(passthrough=tokens), runtime="codex", advisory=False)


@pytest.mark.parametrize(
    "tokens",
    [
        ("--model", "gpt-5.5", "--search"),
        ("--enable", "web_search", "--disable", "feature"),
        ("--config", "model_verbosity=low"),
        ("--image", "resume", "--add-dir", "fork"),
        ("--color", "never", "--output-last-message", "result.txt"),
        ("-mgpt-5.5", "-cmodel_verbosity=low"),
        ("--future-option=value",),
    ],
)
def test_codex_option_values_remain_available(tokens: tuple[str, ...]) -> None:
    args = RuntimeLaunchArgs(passthrough=tokens)
    assert validate_launch_args(args, runtime="codex", advisory=False) is args
