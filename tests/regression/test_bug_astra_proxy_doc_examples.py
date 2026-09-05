"""The proxy guide's creation command and saved configuration must validate."""

import shlex
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from forge.cli.main import main
from forge.config.loader import load_proxy_instance_config_from_dict

pytestmark = pytest.mark.regression

GUIDE = Path(__file__).resolve().parents[2] / "docs/end-user/proxy.md"


def test_proxy_creation_example_accepts_current_defaults() -> None:
    section = GUIDE.read_text().split("### At creation time", 1)[1]
    command = section.split("```bash\n", 1)[1].split("\n```", 1)[0]
    args = shlex.split(command.replace("\\\n", ""))[1:]

    result = CliRunner().invoke(main, [*args, "--no-start"])

    assert result.exit_code == 0, result.output


def test_proxy_yaml_example_accepts_current_models() -> None:
    section = GUIDE.read_text().split("### Proxy file format (user edit surface)", 1)[1]
    config = section.split("```yaml\n", 1)[1].split("\n```", 1)[0]

    load_proxy_instance_config_from_dict(yaml.safe_load(config))
