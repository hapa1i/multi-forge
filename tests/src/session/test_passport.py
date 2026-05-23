"""Tests for the memory-doc passport model.

Covers: strategy constants, frontmatter parsing/serialization, passport
validation, doc resolution, writer validation, flag-vs-passport overrides,
and synthesis.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.exceptions import PassportError
from forge.session.models import DesignatedDoc
from forge.session.passport import (
    PASSPORT_VERSION,
    STRATEGY_INSTRUCTIONS,
    VALID_STRATEGY_NAMES,
    MemoryStrategy,
    Passport,
    PassportUpdate,
    check_shadow_path_collision,
    check_writer_access,
    derive_shadow_path,
    extract_frontmatter,
    parse_passport,
    read_passport,
    resolve_doc_spec,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    validate_writer_spec,
    write_passport,
)

# ---------------------------------------------------------------------------
# TestMemoryStrategy
# ---------------------------------------------------------------------------


class TestMemoryStrategy:
    def test_has_exactly_seven_values(self) -> None:
        assert len(MemoryStrategy) == 7

    def test_valid_strategy_names_matches_enum(self) -> None:
        assert VALID_STRATEGY_NAMES == frozenset(s.value for s in MemoryStrategy)

    def test_strategy_instructions_has_all_entries(self) -> None:
        for name in VALID_STRATEGY_NAMES:
            assert name in STRATEGY_INSTRUCTIONS

    def test_strategy_instructions_are_non_empty(self) -> None:
        for name, instr in STRATEGY_INSTRUCTIONS.items():
            assert isinstance(instr, str) and len(instr) > 0, f"Empty instruction for {name}"


# ---------------------------------------------------------------------------
# TestExtractFrontmatter
# ---------------------------------------------------------------------------


class TestExtractFrontmatter:
    def test_valid_frontmatter(self) -> None:
        text = "---\ntitle: Hello\n---\n# Body\n"
        fm, body = extract_frontmatter(text)
        assert fm == {"title": "Hello"}
        assert body == "# Body\n"

    def test_no_frontmatter(self) -> None:
        text = "# Just a heading\nSome content.\n"
        fm, body = extract_frontmatter(text)
        assert fm is None
        assert body == text

    def test_empty_frontmatter_returns_empty_dict(self) -> None:
        text = "---\n\n---\n# Body\n"
        fm, body = extract_frontmatter(text)
        assert fm == {}
        assert body == "# Body\n"

    def test_non_forge_memory_keys_preserved(self) -> None:
        text = "---\ntitle: Test\nauthor: Jane\n---\nBody text\n"
        fm, body = extract_frontmatter(text)
        assert fm is not None
        assert fm["title"] == "Test"
        assert fm["author"] == "Jane"
        assert body == "Body text\n"

    def test_malformed_yaml_raises_passport_error(self) -> None:
        text = "---\n: invalid: yaml: [[\n---\nBody\n"
        with pytest.raises(PassportError, match="malformed YAML"):
            extract_frontmatter(text)


# ---------------------------------------------------------------------------
# TestParsePassport
# ---------------------------------------------------------------------------


class TestParsePassport:
    def test_valid_changelog_passport(self) -> None:
        data = {
            "version": 1,
            "intent": "Completed-work record",
            "captures": ["completed work"],
            "excludes": ["pending tasks"],
            "update": {
                "strategy": "changelog",
                "mode": "direct",
                "writers": "all-sessions",
            },
        }
        p = parse_passport(data)
        assert p.version == 1
        assert p.intent == "Completed-work record"
        assert p.captures == ["completed work"]
        assert p.excludes == ["pending tasks"]
        assert p.update.strategy == "changelog"
        assert p.update.mode == "direct"
        assert p.update.writers == "all-sessions"

    def test_valid_shadow_only_passport(self) -> None:
        data = {
            "version": 1,
            "intent": "Proposed notes for human review",
            "update": {
                "strategy": "suggested",
                "mode": "shadow-only",
                "shadow_path": ".forge/memory/suggested.md",
                "writers": "all-sessions",
                "approval": "human-promoted",
            },
        }
        p = parse_passport(data)
        assert p.update.mode == "shadow-only"
        assert p.update.shadow_path == ".forge/memory/suggested.md"
        assert p.update.approval == "human-promoted"

    def test_unknown_approval_raises(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"approval": "manual-review"},
        }
        with pytest.raises(PassportError, match="unknown approval.*manual-review"):
            parse_passport(data)

    def test_missing_version_raises(self) -> None:
        with pytest.raises(PassportError, match="version.*required"):
            parse_passport({"intent": "Test"})

    def test_future_version_raises_with_upgrade_hint(self) -> None:
        with pytest.raises(PassportError, match="upgrade"):
            parse_passport({"version": 2, "intent": "Test"})

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(PassportError, match="invalid version"):
            parse_passport({"version": 0, "intent": "Test"})

    def test_missing_intent_raises(self) -> None:
        with pytest.raises(PassportError, match="intent.*required"):
            parse_passport({"version": 1})

    def test_empty_intent_raises(self) -> None:
        with pytest.raises(PassportError, match="non-empty string"):
            parse_passport({"version": 1, "intent": ""})

    def test_missing_update_section_uses_defaults(self) -> None:
        p = parse_passport({"version": 1, "intent": "Minimal doc"})
        assert p.update.strategy == "generic"
        assert p.update.mode == "direct"
        assert p.update.writers == "all-sessions"
        assert p.update.inherit_on_fork is True

    def test_unknown_strategy_raises(self) -> None:
        data = {"version": 1, "intent": "Test", "update": {"strategy": "changelg"}}
        with pytest.raises(PassportError, match="unknown strategy.*changelg"):
            parse_passport(data)

    def test_unknown_mode_raises(self) -> None:
        data = {"version": 1, "intent": "Test", "update": {"mode": "append"}}
        with pytest.raises(PassportError, match="unknown mode"):
            parse_passport(data)

    def test_shadow_only_without_shadow_path_raises(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"strategy": "suggested", "mode": "shadow-only"},
        }
        with pytest.raises(PassportError, match="shadow_path.*required"):
            parse_passport(data)

    def test_direct_with_shadow_path_raises(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"mode": "direct", "shadow_path": "x.md"},
        }
        with pytest.raises(PassportError, match="shadow_path.*not allowed"):
            parse_passport(data)

    def test_unknown_top_level_keys_rejected(self) -> None:
        data = {"version": 1, "intent": "Test", "extra_field": True}
        with pytest.raises(PassportError, match="unknown fields.*extra_field"):
            parse_passport(data)

    def test_unknown_update_keys_rejected(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"strategy": "generic", "unknown_key": 42},
        }
        with pytest.raises(PassportError, match="unknown fields.*unknown_key"):
            parse_passport(data)

    def test_lineage_writer_rejected(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"writers": "lineage:planner"},
        }
        with pytest.raises(PassportError, match="lineage.*not supported"):
            parse_passport(data)

    def test_role_writer_rejected(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"writers": "role:reviewer"},
        }
        with pytest.raises(PassportError, match="role.*not supported"):
            parse_passport(data)

    def test_all_sessions_writer_accepted(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"writers": "all-sessions"},
        }
        p = parse_passport(data)
        assert p.update.writers == "all-sessions"

    def test_exact_session_name_writer_accepted(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"writers": "planner"},
        }
        p = parse_passport(data)
        assert p.update.writers == "planner"

    def test_non_dict_forge_memory_raises(self) -> None:
        with pytest.raises(PassportError, match="must be a mapping"):
            parse_passport(None)  # type: ignore[arg-type]

    def test_list_forge_memory_raises(self) -> None:
        with pytest.raises(PassportError, match="must be a mapping"):
            parse_passport(["version", 1])  # type: ignore[arg-type]

    def test_string_forge_memory_raises(self) -> None:
        with pytest.raises(PassportError, match="must be a mapping"):
            parse_passport("just a string")  # type: ignore[arg-type]

    def test_invalid_session_name_writer_rejected(self) -> None:
        data = {
            "version": 1,
            "intent": "Test",
            "update": {"writers": "IN-VALID"},
        }
        with pytest.raises(PassportError, match="invalid session name"):
            parse_passport(data)


# ---------------------------------------------------------------------------
# TestReadPassport
# ---------------------------------------------------------------------------


class TestReadPassport:
    def test_read_from_file_with_passport(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  version: 1\n  intent: Test doc\n---\n# Content\n")
        p = read_passport(doc)
        assert p is not None
        assert p.intent == "Test doc"

    def test_file_without_passport_returns_none(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# Just a doc\nNo frontmatter here.\n")
        assert read_passport(doc) is None

    def test_file_with_non_forge_frontmatter_returns_none(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\ntitle: My Doc\n---\n# Content\n")
        assert read_passport(doc) is None

    def test_malformed_passport_raises(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  version: 99\n  intent: Test\n---\n# Content\n")
        with pytest.raises(PassportError, match="upgrade"):
            read_passport(doc)

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory: [invalid: yaml\n---\n# Content\n")
        with pytest.raises(PassportError, match="malformed YAML"):
            read_passport(doc)

    def test_bare_forge_memory_key_raises(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n---\n# Content\n")
        with pytest.raises(PassportError, match="must be a mapping"):
            read_passport(doc)

    def test_list_forge_memory_raises(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  - item1\n  - item2\n---\n# Content\n")
        with pytest.raises(PassportError, match="must be a mapping"):
            read_passport(doc)


# ---------------------------------------------------------------------------
# TestWritePassport
# ---------------------------------------------------------------------------


class TestWritePassport:
    def _make_passport(self, **update_kwargs: object) -> Passport:
        return Passport(
            version=1,
            intent="Test doc",
            update=PassportUpdate(**update_kwargs),  # type: ignore[arg-type]
        )

    def test_write_to_file_with_no_frontmatter(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# My Document\nContent here.\n")
        write_passport(doc, self._make_passport(strategy="changelog"))
        text = doc.read_text()
        assert text.startswith("---\n")
        assert "forge_memory:" in text
        assert "strategy: changelog" in text
        assert "# My Document\nContent here.\n" in text

    def test_replace_existing_passport(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  version: 1\n  intent: Old\n---\n# Body\n")
        write_passport(doc, self._make_passport(strategy="checklist"))
        text = doc.read_text()
        assert "strategy: checklist" in text
        assert "Old" not in text
        assert "# Body\n" in text

    def test_preserves_non_forge_memory_keys(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\ntitle: Keep Me\n---\n# Body\n")
        write_passport(doc, self._make_passport())
        text = doc.read_text()
        assert "title: Keep Me" in text
        assert "forge_memory:" in text

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        body = "# Heading\n\nParagraph with *markdown*.\n\n- Item 1\n- Item 2\n"
        doc = tmp_path / "doc.md"
        doc.write_text(body)
        write_passport(doc, self._make_passport())
        text = doc.read_text()
        assert body in text

    def test_round_trip(self, tmp_path: Path) -> None:
        original = Passport(
            version=1,
            intent="Round-trip test",
            captures=["a", "b"],
            excludes=["c"],
            update=PassportUpdate(
                strategy="changelog",
                mode="direct",
                writers="planner",
                inherit_on_fork=False,
            ),
        )
        doc = tmp_path / "doc.md"
        doc.write_text("# Doc\n")
        write_passport(doc, original)
        restored = read_passport(doc)
        assert restored is not None
        assert restored.version == original.version
        assert restored.intent == original.intent
        assert restored.captures == original.captures
        assert restored.excludes == original.excludes
        assert restored.update.strategy == original.update.strategy
        assert restored.update.writers == original.update.writers
        assert restored.update.inherit_on_fork is False

    def test_none_fields_omitted_from_output(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# Doc\n")
        write_passport(doc, self._make_passport())
        text = doc.read_text()
        assert "shadow_path" not in text
        assert "approval" not in text
        assert "compact_when" not in text
        assert "instruction" not in text


# ---------------------------------------------------------------------------
# TestSynthesizePassport
# ---------------------------------------------------------------------------


class TestSynthesizePassport:
    def test_with_explicit_intent(self) -> None:
        p = synthesize_passport(strategy="changelog", intent="Custom intent")
        assert p.intent == "Custom intent"
        assert p.update.strategy == "changelog"

    def test_auto_generated_intent_from_strategy(self) -> None:
        p = synthesize_passport(strategy="changelog")
        assert p.intent  # non-empty
        assert p.version == PASSPORT_VERSION

    def test_shadow_only_mode_with_shadow_path(self) -> None:
        p = synthesize_passport(
            strategy="suggested",
            update_mode="shadow-only",
            shadow_path=".forge/memory/suggested.md",
        )
        assert p.update.mode == "shadow-only"
        assert p.update.shadow_path == ".forge/memory/suggested.md"

    def test_always_has_explicit_update_section(self) -> None:
        p = synthesize_passport(strategy="generic")
        assert p.update is not None
        assert p.update.strategy == "generic"
        assert p.update.mode == "direct"
        assert p.update.writers == "all-sessions"

    def test_invalid_strategy_raises(self) -> None:
        with pytest.raises(PassportError, match="unknown strategy"):
            synthesize_passport(strategy="invalid")

    def test_direct_with_shadow_path_raises(self) -> None:
        with pytest.raises(PassportError, match="shadow_path.*not allowed"):
            synthesize_passport(strategy="generic", update_mode="direct", shadow_path="shadow.md")


# ---------------------------------------------------------------------------
# TestResolvePassportSource
# ---------------------------------------------------------------------------


class TestResolvePassportSource:
    def test_direct_doc_returns_path(self) -> None:
        doc = DesignatedDoc(path="docs/changelog.md", strategy="changelog")
        assert resolve_passport_source(doc) == "docs/changelog.md"

    def test_shadow_doc_returns_shadows(self) -> None:
        doc = DesignatedDoc(
            path=".forge/memory/suggested.md",
            strategy="suggested",
            shadows="docs/impl_notes.md",
        )
        assert resolve_passport_source(doc) == "docs/impl_notes.md"


# ---------------------------------------------------------------------------
# TestResolveDocSpec
# ---------------------------------------------------------------------------


class TestResolveDocSpec:
    def test_direct_doc_without_passport(self) -> None:
        doc = DesignatedDoc(path="docs/changelog.md", strategy="changelog")
        spec = resolve_doc_spec(doc, None)
        assert spec.write_path == "docs/changelog.md"
        assert spec.official_path is None
        assert "accomplishments" in spec.strategy_instruction
        assert spec.custom_instruction is None
        assert spec.intent is None

    def test_direct_doc_with_passport_strategy_wins(self) -> None:
        doc = DesignatedDoc(path="docs/changelog.md", strategy="generic")
        passport = Passport(
            version=1,
            intent="Completed work",
            update=PassportUpdate(strategy="changelog"),
        )
        spec = resolve_doc_spec(doc, passport)
        assert "accomplishments" in spec.strategy_instruction  # changelog, not generic
        assert spec.intent == "Completed work"

    def test_shadow_doc_with_passport_shadow_path_overrides(self) -> None:
        doc = DesignatedDoc(
            path=".forge/memory/old_shadow.md",
            strategy="suggested",
            shadows="docs/impl_notes.md",
        )
        passport = Passport(
            version=1,
            intent="Durable memory",
            update=PassportUpdate(
                strategy="suggested",
                mode="shadow-only",
                shadow_path=".forge/memory/new_shadow.md",
            ),
        )
        spec = resolve_doc_spec(doc, passport)
        assert spec.write_path == ".forge/memory/new_shadow.md"
        assert spec.official_path == "docs/impl_notes.md"

    def test_passported_shadow_manifest_direct_mode_writes_official_doc(self) -> None:
        doc = DesignatedDoc(
            path=".forge/memory/shadow.md",
            strategy="suggested",
            shadows="docs/impl_notes.md",
        )
        passport = Passport(
            version=1,
            intent="Official doc",
            update=PassportUpdate(strategy="changelog", mode="direct"),
        )
        spec = resolve_doc_spec(doc, passport)
        assert spec.write_path == "docs/impl_notes.md"
        assert spec.official_path is None
        assert "accomplishments" in spec.strategy_instruction

    def test_passport_fields_carried_through(self) -> None:
        doc = DesignatedDoc(path="docs/notes.md")
        passport = Passport(
            version=1,
            intent="Project docs",
            captures=["decisions"],
            excludes=["raw output"],
            update=PassportUpdate(
                instruction="Be concise",
                compact_when="over 200 lines",
                approval="human-promoted",
            ),
        )
        spec = resolve_doc_spec(doc, passport)
        assert spec.intent == "Project docs"
        assert spec.captures == ["decisions"]
        assert spec.excludes == ["raw output"]
        assert spec.custom_instruction == "Be concise"
        assert spec.compact_when == "over 200 lines"
        assert spec.approval == "human-promoted"

    def test_passport_less_doc_produces_valid_fallback(self) -> None:
        doc = DesignatedDoc(
            path=".forge/memory/shadow.md",
            strategy="suggested",
            shadows="docs/official.md",
        )
        spec = resolve_doc_spec(doc, None)
        assert spec.write_path == ".forge/memory/shadow.md"
        assert spec.official_path == "docs/official.md"
        assert spec.captures == []
        assert spec.excludes == []


# ---------------------------------------------------------------------------
# TestResolveWithOverrides
# ---------------------------------------------------------------------------


class TestResolveWithOverrides:
    def _base_passport(self) -> Passport:
        return Passport(
            version=1,
            intent="Test",
            update=PassportUpdate(strategy="generic", mode="direct"),
        )

    def test_no_overrides_returns_deep_copy(self) -> None:
        original = self._base_passport()
        resolved, warnings = resolve_with_overrides(original)
        assert warnings == []
        assert resolved.update.strategy == "generic"
        assert resolved is not original  # deep copy

    def test_strategy_override_warns(self) -> None:
        resolved, warnings = resolve_with_overrides(self._base_passport(), strategy="changelog")
        assert resolved.update.strategy == "changelog"
        assert len(warnings) == 1
        assert "changelog" in warnings[0]
        assert "generic" in warnings[0]

    def test_update_mode_override_warns(self) -> None:
        p = Passport(
            version=1,
            intent="Test",
            update=PassportUpdate(
                strategy="suggested",
                mode="direct",
                shadow_path=None,
            ),
        )
        # shadow-only requires shadow_path; provide one via the passport
        p.update.shadow_path = ".forge/memory/shadow.md"
        resolved, warnings = resolve_with_overrides(p, update_mode="shadow-only")
        assert resolved.update.mode == "shadow-only"
        assert len(warnings) == 1

    def test_direct_mode_override_clears_shadow_path(self) -> None:
        p = Passport(
            version=1,
            intent="Test",
            update=PassportUpdate(
                strategy="suggested",
                mode="shadow-only",
                shadow_path=".forge/memory/shadow.md",
            ),
        )
        resolved, warnings = resolve_with_overrides(p, update_mode="direct")
        assert resolved.update.mode == "direct"
        assert resolved.update.shadow_path is None
        assert len(warnings) == 2
        assert "shadow_path" in warnings[1]

    def test_multiple_overrides_produce_multiple_warnings(self) -> None:
        _, warnings = resolve_with_overrides(self._base_passport(), strategy="changelog", writers="planner")
        assert len(warnings) == 2

    def test_original_passport_unchanged_after_override(self) -> None:
        original = self._base_passport()
        resolve_with_overrides(original, strategy="changelog")
        assert original.update.strategy == "generic"

    def test_shadow_only_without_shadow_path_raises(self) -> None:
        with pytest.raises(PassportError, match="shadow_path.*required"):
            resolve_with_overrides(self._base_passport(), update_mode="shadow-only")

    def test_invalid_direct_with_shadow_path_raises(self) -> None:
        p = Passport(
            version=1,
            intent="Test",
            update=PassportUpdate(mode="direct", shadow_path=".forge/memory/shadow.md"),
        )
        with pytest.raises(PassportError, match="shadow_path.*not allowed"):
            resolve_with_overrides(p)

    def test_invalid_strategy_override_raises(self) -> None:
        with pytest.raises(PassportError, match="unknown strategy"):
            resolve_with_overrides(self._base_passport(), strategy="bogus")

    def test_invalid_mode_override_raises(self) -> None:
        with pytest.raises(PassportError, match="unknown mode"):
            resolve_with_overrides(self._base_passport(), update_mode="append")

    def test_shadow_path_override_warns(self) -> None:
        p = Passport(
            version=1,
            intent="Test",
            update=PassportUpdate(
                strategy="suggested",
                mode="shadow-only",
                shadow_path=".forge/memory/old.md",
            ),
        )
        resolved, warnings = resolve_with_overrides(p, shadow_path=".forge/memory/new.md")
        assert resolved.update.shadow_path == ".forge/memory/new.md"
        assert len(warnings) == 1
        assert "old.md" in warnings[0]

    def test_mode_and_shadow_path_override_together(self) -> None:
        p = self._base_passport()
        resolved, warnings = resolve_with_overrides(
            p,
            update_mode="shadow-only",
            shadow_path=".forge/memory/shadow.md",
        )
        assert resolved.update.mode == "shadow-only"
        assert resolved.update.shadow_path == ".forge/memory/shadow.md"
        # 1 warning for mode override; shadow_path has no old value to override
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# TestDeriveShadowPath
# ---------------------------------------------------------------------------


class TestDeriveShadowPath:
    def test_basic_with_parent_prefix(self) -> None:
        assert derive_shadow_path("docs/status/impl_notes.md") == ".forge/memory/suggested_status_impl_notes.md"

    def test_top_level_file_no_prefix(self) -> None:
        assert derive_shadow_path("README.md") == ".forge/memory/suggested_README.md"

    def test_single_parent_dir(self) -> None:
        assert derive_shadow_path("docs/checklist.md") == ".forge/memory/suggested_docs_checklist.md"

    def test_deeply_nested_uses_immediate_parent(self) -> None:
        assert derive_shadow_path("a/b/c/deep/notes.md") == ".forge/memory/suggested_deep_notes.md"


# ---------------------------------------------------------------------------
# TestShadowPathCollision
# ---------------------------------------------------------------------------


class TestShadowPathCollision:
    def test_no_existing_docs_safe(self) -> None:
        assert check_shadow_path_collision(".forge/memory/suggested_notes.md", "docs/notes.md", []) is None

    def test_same_official_retrack_safe(self) -> None:
        existing = [
            DesignatedDoc(
                path=".forge/memory/suggested_status_notes.md",
                strategy="suggested",
                shadows="docs/status/notes.md",
            ),
        ]
        result = check_shadow_path_collision(
            ".forge/memory/suggested_status_notes.md",
            "docs/status/notes.md",
            existing,
        )
        assert result is None

    def test_derived_collision_different_officials(self) -> None:
        existing = [
            DesignatedDoc(
                path=".forge/memory/suggested_status_notes.md",
                strategy="suggested",
                shadows="a/status/notes.md",
            ),
        ]
        result = check_shadow_path_collision(
            ".forge/memory/suggested_status_notes.md",
            "b/status/notes.md",
            existing,
        )
        assert result is not None
        assert "--shadow" in result
        assert "a/status/notes.md" in result

    def test_explicit_shadow_collision(self) -> None:
        existing = [
            DesignatedDoc(
                path=".forge/memory/custom.md",
                strategy="suggested",
                shadows="docs/a.md",
            ),
        ]
        result = check_shadow_path_collision(
            ".forge/memory/custom.md",
            "docs/b.md",
            existing,
        )
        assert result is not None
        assert "--shadow" in result

    def test_collision_with_direct_doc(self) -> None:
        existing = [
            DesignatedDoc(path=".forge/memory/suggested_notes.md", strategy="generic"),
        ]
        result = check_shadow_path_collision(
            ".forge/memory/suggested_notes.md",
            "docs/notes.md",
            existing,
        )
        assert result is not None
        assert "direct doc" in result


# ---------------------------------------------------------------------------
# TestWriterValidation
# ---------------------------------------------------------------------------


class TestWriterValidation:
    def test_all_sessions_accepted(self) -> None:
        validate_writer_spec("all-sessions")

    def test_exact_session_name_accepted(self) -> None:
        validate_writer_spec("planner")
        validate_writer_spec("feature-auth-v2")

    def test_lineage_prefix_rejected(self) -> None:
        with pytest.raises(PassportError, match="lineage.*not supported"):
            validate_writer_spec("lineage:planner")

    def test_role_prefix_rejected(self) -> None:
        with pytest.raises(PassportError, match="role.*not supported"):
            validate_writer_spec("role:reviewer")

    def test_none_rejected(self) -> None:
        with pytest.raises(PassportError, match="none.*not.*valid"):
            validate_writer_spec("none")

    def test_invalid_name_format_rejected(self) -> None:
        with pytest.raises(PassportError, match="invalid session name"):
            validate_writer_spec("UPPERCASE")


# ---------------------------------------------------------------------------
# TestCheckWriterAccess
# ---------------------------------------------------------------------------


class TestCheckWriterAccess:
    def test_all_sessions_allows_any(self) -> None:
        assert check_writer_access("all-sessions", "anything") is True

    def test_exact_match_allows(self) -> None:
        assert check_writer_access("planner", "planner") is True

    def test_non_match_denies(self) -> None:
        assert check_writer_access("planner", "executor") is False
