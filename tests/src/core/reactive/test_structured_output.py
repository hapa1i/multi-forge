"""Tests for forge.core.reactive.structured_output."""

from __future__ import annotations

from forge.core.reactive.structured_output import extract_json_from_response


class TestExtractJsonFromResponse:
    def test_json_code_fence(self):
        response = '```json\n{"verdict": "aligned", "confidence": 0.95}\n```'
        result = extract_json_from_response(response)
        assert result == {"verdict": "aligned", "confidence": 0.95}

    def test_bare_code_fence(self):
        response = '```\n{"verdict": "divergent"}\n```'
        result = extract_json_from_response(response)
        assert result == {"verdict": "divergent"}

    def test_raw_json(self):
        response = '{"verdict": "aligned", "violations": []}'
        result = extract_json_from_response(response)
        assert result == {"verdict": "aligned", "violations": []}

    def test_json_with_surrounding_prose(self):
        response = "Here's my analysis:\n\n" '```json\n{"verdict": "aligned"}\n```\n\n' "The action looks good."
        result = extract_json_from_response(response)
        assert result == {"verdict": "aligned"}

    def test_multiple_fences_returns_first_valid(self):
        response = '```\nnot json\n```\n\n```json\n{"key": "value"}\n```'
        result = extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_malformed_json_returns_none(self):
        response = "```json\n{invalid json}\n```"
        result = extract_json_from_response(response)
        assert result is None

    def test_empty_response_returns_none(self):
        assert extract_json_from_response("") is None

    def test_no_json_at_all_returns_none(self):
        response = "This is just a text response with no JSON."
        assert extract_json_from_response(response) is None

    def test_json_array_not_dict_returns_none(self):
        """Only dicts are returned; arrays are not valid structured output."""
        response = '```json\n["a", "b"]\n```'
        assert extract_json_from_response(response) is None

    def test_case_insensitive_fence(self):
        response = '```JSON\n{"key": "value"}\n```'
        result = extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_deeply_nested_json(self):
        """Deeply nested JSON objects parse correctly."""
        import json

        nested = {"level": 1, "child": {"level": 2, "child": {"level": 3, "data": [1, 2, 3]}}}
        response = f"```json\n{json.dumps(nested)}\n```"
        result = extract_json_from_response(response)
        assert result["child"]["child"]["level"] == 3
        assert result["child"]["child"]["data"] == [1, 2, 3]

    def test_large_json_response(self):
        """JSON responses >10KB parse correctly."""
        import json

        large = {"items": [{"id": i, "data": "x" * 100} for i in range(100)]}
        payload = json.dumps(large)
        assert len(payload) > 10_000
        response = f"```json\n{payload}\n```"
        result = extract_json_from_response(response)
        assert len(result["items"]) == 100
        assert result["items"][99]["id"] == 99
