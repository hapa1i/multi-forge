"""QA cannot certify release evidence without the required provider infrastructure."""

import pytest

from tests.src.skills.test_qa_run_metrics import _artifact, _compute, _state

pytestmark = pytest.mark.regression
REQUIRED = ("INFRA_API_KEY", "INFRA_ANTHROPIC_API", "INFRA_CODEX", "INFRA_OPENROUTER")


def _ready_state():
    state = _state()
    state["vars"].update(dict.fromkeys(REQUIRED, "true"))
    return state


@pytest.mark.parametrize("profile", [None, "remote-litellm", "unknown"])
def test_release_requires_recorded_openrouter_profile(profile):
    artifact = _artifact()
    artifact.pop("provider_profile", None)
    if profile is not None:
        artifact["provider_profile"] = profile
    result = _compute(artifact=artifact, state=_ready_state())
    assert result["verdict"] == "incomplete"
    assert result["artifact_release_capable"] is False


@pytest.mark.parametrize("variable", REQUIRED)
@pytest.mark.parametrize("value", [None, "false", "TRUE"])
def test_release_requires_explicit_positive_infrastructure(variable, value):
    artifact = _artifact()
    artifact["provider_profile"] = "openrouter"
    state = _ready_state()
    state["vars"].pop(variable)
    if value is not None:
        state["vars"][variable] = value
    result = _compute(artifact=artifact, state=state)
    assert result["verdict"] == "incomplete"
    assert result["artifact_release_capable"] is False
