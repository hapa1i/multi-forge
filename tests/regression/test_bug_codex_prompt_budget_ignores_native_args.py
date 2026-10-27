"""Native options and child environment must share ARG_MAX with the initial prompt."""

import os
import struct
import sys

import pytest

from forge.core.runtime.launch_args import RuntimeLaunchArgs, validate_launch_args
from forge.session.codex_invoke import max_initial_prompt_bytes

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("many_options", [False, True], ids=["large-config", "many-pointers"])
def test_native_options_are_counted_beyond_fixed_headroom(monkeypatch: pytest.MonkeyPatch, many_options: bool) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "sysconf", {"SC_ARG_MAX": 1024 * 1024}.__getitem__)
    native = (
        ("-c", "history.max_bytes=100") * 4096
        if many_options
        else ("-c", 'developer_instructions="' + "é" * 16384 + '"')
    )
    args = validate_launch_args(RuntimeLaunchArgs(passthrough=native), runtime="codex", advisory=False).runtime_argv(
        "codex"
    )
    base = ["codex", "--sandbox", "workspace-write"]
    baseline = max_initial_prompt_bytes(argv=base, env={})
    limit = max_initial_prompt_bytes(argv=[*base, *args], env={})

    assert baseline is not None and limit is not None
    assert baseline - limit == sum(len(os.fsencode(arg)) + 1 + struct.calcsize("P") for arg in args)
    assert baseline - limit > 16 * 1024


def test_child_environment_is_counted_instead_of_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "sysconf", {"SC_ARG_MAX": 1024 * 1024}.__getitem__)
    monkeypatch.setattr(os, "environ", {"STRIPPED_FROM_CHILD": "x" * 100_000})
    baseline = max_initial_prompt_bytes(argv=["codex"], env={})
    child_env = {"NATIVE_CHILD_VALUE": "é" * 32_768}
    limit = max_initial_prompt_bytes(argv=["codex"], env=child_env)

    assert baseline is not None and limit is not None
    assert baseline - limit == len("NATIVE_CHILD_VALUE=".encode()) + 65_536 + 1 + struct.calcsize("P")
