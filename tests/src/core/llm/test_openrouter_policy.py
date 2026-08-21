"""Tests for shared OpenRouter request-policy composition."""

from forge.core.llm import ModelHyperparameters, with_openrouter_zdr


def test_requires_zdr_from_none() -> None:
    hp = with_openrouter_zdr(None)

    assert hp.extra == {"openai": {"extra_body": {"provider": {"zdr": True}}}}


def test_forces_zdr_without_clobbering_siblings() -> None:
    base = ModelHyperparameters(
        extra={
            "openai": {
                "user": "forge_run_test",
                "extra_body": {
                    "provider": {"zdr": False, "sort": "price"},
                    "transforms": ["middle-out"],
                },
            }
        }
    )

    hp = with_openrouter_zdr(base)

    assert hp.extra["openai"] == {
        "user": "forge_run_test",
        "extra_body": {
            "provider": {"zdr": True, "sort": "price"},
            "transforms": ["middle-out"],
        },
    }


def test_does_not_mutate_caller() -> None:
    base = ModelHyperparameters(extra={"openai": {"extra_body": {"provider": {"sort": "throughput"}}}})

    with_openrouter_zdr(base)

    assert base.extra == {"openai": {"extra_body": {"provider": {"sort": "throughput"}}}}
