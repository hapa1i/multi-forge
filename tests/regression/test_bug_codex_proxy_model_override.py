"""The proxy launcher respects the same model precedence when reporting and building argv."""

import pytest

from forge.session.codex_invoke import _build_codex_proxy_argv, passthrough_model

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["-c", 'model="custom/model"'], "custom/model"),
        (["--config", "model = 'custom/model'"], "custom/model"),
        (["--config=model=old", "-cmodel=custom/model"], "custom/model"),
        (["-c", 'model="old"', "-c=model=custom/model"], "custom/model"),
        (["-c", "model=old", "-m", "flag-model", "--config=model=last"], "flag-model"),
        (["--model=flag-model", "-c", "model=last"], "flag-model"),
        (["-c", 'model_alias="other"', "--", "-c", "model=other"], None),
    ],
)
def test_explicit_model_wins_over_proxy_default(args, expected):
    assert passthrough_model(args) == expected
    argv = _build_codex_proxy_argv(
        base_url="http://localhost:1234",
        sandbox="read-only",
        model="default",
        passthrough=args,
    )
    assert ("default" in argv) == (expected is None)
    assert argv[-len(args) :] == args
