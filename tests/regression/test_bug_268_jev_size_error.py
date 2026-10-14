"""PR 268: structured Jev size errors may include additional provider metadata."""

import json

import pytest

from forge.core.judgments.openrouter import status_failure

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "detail,expected",
    [
        ({"error_type": "max_tokens_exceeded", "limit": 32000}, "payload_too_large"),
        ({"error_type": "another_error", "limit": 32000}, "validation"),
        ([{"error_type": "max_tokens_exceeded"}], "validation"),
        ("max_tokens_exceeded", "validation"),
        (None, "validation"),
    ],
)
def test_error_type_survives_extra_fields_without_matching_prose(detail, expected):
    body = {"error": {"message": "HTTP 400: " + json.dumps({"detail": detail})}}
    assert status_failure(400, body) == expected
