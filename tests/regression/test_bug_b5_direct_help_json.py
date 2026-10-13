"""B5 reused Click parsing must not leak eager help into hook stdout."""

import json

import pytest

from forge.cli.hooks import direct_commands
from tests.src.cli.test_native_supervisor import native_setup as native_setup

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("args", [["--help"], ["set", "--help"], ["set", "--bad-option"], ["set", "--runtime"]])
def test_direct_help_and_parse_errors_emit_exactly_one_json_reply(native_setup, capsys, args):
    before = native_setup.manifest_path.read_bytes()
    direct_commands._handle_policy_supervisor(args)
    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert response["decision"] == "block" and response["reason"]
    if "--help" in args:
        assert "--source-runtime" in response["reason"] and "Usage:" in response["reason"]
    assert captured.err == ""
    assert native_setup.manifest_path.read_bytes() == before
