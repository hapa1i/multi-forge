"""Tests for the wire-shape vocabulary leaf."""

from typing import get_args

from forge.core.wire_shapes import (
    ANTHROPIC_PASSTHROUGH,
    DEFAULT_WIRE_SHAPE,
    OPENAI_RESPONSES_PASSTHROUGH,
    OPENAI_TRANSLATED,
    PASSTHROUGH_WIRE_SHAPES,
    VALID_WIRE_SHAPES,
    WireShape,
)


def test_valid_shapes_are_the_three_constants():
    assert VALID_WIRE_SHAPES == (
        OPENAI_TRANSLATED,
        ANTHROPIC_PASSTHROUGH,
        OPENAI_RESPONSES_PASSTHROUGH,
    )


def test_literal_type_matches_valid_tuple():
    assert get_args(WireShape) == VALID_WIRE_SHAPES


def test_default_is_translated_and_valid():
    assert DEFAULT_WIRE_SHAPE == OPENAI_TRANSLATED
    assert DEFAULT_WIRE_SHAPE in VALID_WIRE_SHAPES


def test_passthrough_shapes_are_the_byte_faithful_subset():
    assert PASSTHROUGH_WIRE_SHAPES == (ANTHROPIC_PASSTHROUGH, OPENAI_RESPONSES_PASSTHROUGH)
    assert OPENAI_TRANSLATED not in PASSTHROUGH_WIRE_SHAPES
    assert set(PASSTHROUGH_WIRE_SHAPES) < set(VALID_WIRE_SHAPES)
