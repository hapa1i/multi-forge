"""B5 direct status views must identify native-only supervisors."""

import json

import pytest

from forge.cli.hooks import direct_commands
from tests.fixtures.native_supervisor import THREAD
from tests.src.cli.test_native_supervisor import configure
from tests.src.cli.test_native_supervisor import native_setup as native_setup

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("args", [["status"], ["supervisor"]])
def test_in_session_status_names_the_native_source(native_setup, capsys, args):
    assert configure().exit_code == 0
    direct_commands._handle_cmd_policy({}, args)
    response = json.loads(capsys.readouterr().out)
    assert f"native codex {THREAD}" in response["reason"]
    assert "Supervisor: None" not in response["reason"]
