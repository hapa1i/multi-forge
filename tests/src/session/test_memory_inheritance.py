"""Tests for memory activation inheritance during fork and resume.

Covers: create_shadow_file, apply_memory_inheritance (auto_update-only model).
"""

from __future__ import annotations

import pytest

from forge.session.memory_inheritance import (
    apply_memory_inheritance,
    create_shadow_file,
)
from forge.session.models import (
    MemoryIntent,
    MemoryWriterConfig,
    create_session_state,
)

# ---------------------------------------------------------------------------
# create_shadow_file
# ---------------------------------------------------------------------------


class TestCreateShadowFile:
    def test_creates_forge_memory_shadow(self, tmp_path):
        shadow = ".forge/memory/suggested_notes.md"
        assert create_shadow_file(shadow, tmp_path) is True
        assert (tmp_path / shadow).is_file()

    def test_existing_file_is_noop(self, tmp_path):
        shadow = ".forge/memory/suggested_notes.md"
        (tmp_path / shadow).parent.mkdir(parents=True)
        (tmp_path / shadow).write_text("existing")
        assert create_shadow_file(shadow, tmp_path) is False
        assert (tmp_path / shadow).read_text() == "existing"

    def test_non_forge_memory_returns_false(self, tmp_path):
        assert create_shadow_file("docs/notes.md", tmp_path) is False

    def test_unsafe_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unsafe"):
            create_shadow_file("../../etc/shadow", tmp_path)

    def test_creates_parent_directories(self, tmp_path):
        shadow = ".forge/memory/deep/nested/suggested.md"
        assert create_shadow_file(shadow, tmp_path) is True
        assert (tmp_path / shadow).is_file()


# ---------------------------------------------------------------------------
# apply_memory_inheritance (auto_update-only model)
# ---------------------------------------------------------------------------


class TestApplyMemoryInheritance:
    def test_inherits_parent_auto_update(self):
        parent = create_session_state(name="parent")
        parent.intent.memory = MemoryIntent(
            auto_update=MemoryWriterConfig(enabled=True, mode="augment"),
        )
        child = create_session_state(name="child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.enabled is True
        assert child.intent.memory.auto_update.mode == "augment"

    def test_no_parent_memory_gives_none(self):
        parent = create_session_state(name="parent")
        assert parent.intent.memory is None
        child = create_session_state(name="child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is None

    def test_memory_flag_on_forces_enabled(self):
        parent = create_session_state(name="parent")
        child = create_session_state(name="child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            memory_flag=True,
        )

        assert child.intent.memory is not None
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.enabled is True

    def test_memory_flag_off_forces_disabled(self):
        """memory_flag=False produces an explicit MemoryWriterConfig(enabled=False), not None."""
        parent = create_session_state(name="parent")
        parent.intent.memory = MemoryIntent(
            auto_update=MemoryWriterConfig(enabled=True, mode="augment"),
        )
        child = create_session_state(name="child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            memory_flag=False,
        )

        assert child.intent.memory is not None
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.enabled is False

    def test_memory_flag_on_uses_parent_config(self):
        """memory_flag=True inherits parent's mode and other MemoryWriterConfig fields."""
        parent = create_session_state(name="parent")
        parent.intent.memory = MemoryIntent(
            auto_update=MemoryWriterConfig(enabled=True, mode="review-only", min_turns=10),
        )
        child = create_session_state(name="child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            memory_flag=True,
        )

        assert child.intent.memory is not None
        au = child.intent.memory.auto_update
        assert au is not None
        assert au.enabled is True
        assert au.mode == "review-only"
        assert au.min_turns == 10

    def test_memory_flag_on_no_parent_uses_defaults(self):
        """memory_flag=True with no parent auto_update falls back to MemoryWriterConfig defaults."""
        parent = create_session_state(name="parent")
        assert parent.intent.memory is None
        child = create_session_state(name="child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            memory_flag=True,
        )

        assert child.intent.memory is not None
        au = child.intent.memory.auto_update
        assert au is not None
        assert au.enabled is True
        # Defaults from MemoryWriterConfig
        assert au.mode == "augment"
        assert au.min_turns == 5

    def test_does_not_leak_unrelated_fields(self):
        """Only auto_update is inherited; auto_recall, tags, etc. stay at defaults."""
        parent = create_session_state(name="parent")
        parent.intent.memory = MemoryIntent(
            auto_recall=True,
            tags=["x"],
            auto_update=MemoryWriterConfig(enabled=True, mode="augment"),
        )
        child = create_session_state(name="child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        # auto_update is inherited
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.enabled is True
        # Unrelated fields are NOT inherited (fresh MemoryIntent defaults)
        assert child.intent.memory.auto_recall is False
        assert child.intent.memory.tags == []
