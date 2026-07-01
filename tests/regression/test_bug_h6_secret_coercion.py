"""Regression test for H6: _convert_value() silently coerced secrets to wrong types.

Bug: Environment variables with numeric-looking or boolean-looking values were
coerced to int/bool, breaking auth flows that expect opaque strings. For example,
"007" became 7 and "true" became True.

Root cause: env_to_dict() applied _convert_value() (auto int/bool coercion) to ALL
env vars including secrets. Secrets must be opaque strings.

Fix: Removed _convert_value() from secret mappings in config/loader.py. Secrets are
stored as-is via _set_nested() with no type conversion.

Fixed in: src/forge/config/loader.py (action plan Step 1, H6)
"""

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "env_key,config_path,test_value",
    [
        # The *_AUTH_URL mappings were removed in the accidental-complexity cleanup;
        # FORGE_HOME is the surviving env mapping and still must not be type-coerced.
        ("FORGE_HOME", ("session", "forge_home"), "12345"),
        ("FORGE_HOME", ("session", "forge_home"), "007"),
        ("FORGE_HOME", ("session", "forge_home"), "true"),
        ("FORGE_HOME", ("session", "forge_home"), "false"),
        ("FORGE_HOME", ("session", "forge_home"), "0"),
    ],
)
def test_all_secret_mappings_return_strings(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    config_path: tuple,
    test_value: str,
) -> None:
    """Mapped env vars must be preserved as strings, never type-coerced."""
    from forge.config.loader import env_to_dict

    monkeypatch.setenv(env_key, test_value)
    result = env_to_dict()

    # Navigate nested dict
    d = result
    for key in config_path:
        d = d[key]

    assert d == test_value
    assert isinstance(d, str), f"{env_key}={test_value!r} was coerced to {type(d).__name__}"
