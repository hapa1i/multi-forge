"""Tests for the memory-doc passport model.

Covers: strategy constants, frontmatter parsing/serialization, passport
validation, doc resolution, writer validation, flag-vs-passport overrides,
and synthesis.
"""

from __future__ import annotations

import stat
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
    apply_prepared_passport_write,
    check_writer_access,
    derive_shadow_path,
    extract_frontmatter,
    parse_passport,
    prepare_passport_write,
    read_passport,
    remove_passport,
    resolve_doc_spec,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    upgrade_passport_envelope,
    validate_okf_memory_path,
    validate_writer_spec,
    write_passport,
)

# ---------------------------------------------------------------------------
# TestMemoryStrategy
# ---------------------------------------------------------------------------


class TestMemoryStrategy:
    def test_has_exactly_four_values(self) -> None:
        assert len(MemoryStrategy) == 4

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

    @pytest.mark.parametrize(
        "text",
        [
            "\ufeff---\ntitle: BOM\n---\n# Body\n",
            "---\ntitle: EOF\n---",
        ],
    )
    def test_unsupported_delimiter_variants_keep_permissive_read_behavior(self, text: str) -> None:
        fm, body = extract_frontmatter(text)
        assert fm is None
        assert body == text


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
                "strategy": "generic",
                "mode": "shadow-only",
                "shadow_path": ".forge/memory/shadow.md",
                "writers": "all-sessions",
                "approval": "human-promoted",
            },
        }
        p = parse_passport(data)
        assert p.update.mode == "shadow-only"
        assert p.update.shadow_path == ".forge/memory/shadow.md"
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

    def test_bool_version_raises(self) -> None:
        with pytest.raises(PassportError, match="must be an integer"):
            parse_passport({"version": True, "intent": "Test"})

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
            "update": {"strategy": "generic", "mode": "shadow-only"},
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

    def test_legacy_inherit_on_fork_accepted_and_ignored(self) -> None:
        """An old passport carrying update.inherit_on_fork still parses (accept-and-ignore)."""
        passport = parse_passport(
            {
                "version": 1,
                "intent": "Test",
                "update": {"writers": "all-sessions", "inherit_on_fork": False},
            }
        )
        assert passport.update.writers == "all-sessions"
        assert not hasattr(passport.update, "inherit_on_fork")

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
# TestRemovePassport
# ---------------------------------------------------------------------------


class TestRemovePassport:
    def test_removes_only_passport_when_only_frontmatter_key(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        body = "# Body\nContent\n"
        doc.write_text("---\nforge_memory:\n  version: 1\n  intent: Test\n---\n" + body)

        assert remove_passport(doc) is True
        assert doc.read_text() == body

    def test_preserves_unrelated_frontmatter_keys(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\ntitle: Keep Me\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Body\n")

        assert remove_passport(doc) is True
        text = doc.read_text()
        assert text.startswith("---\n")
        assert "title: Keep Me" in text
        assert "forge_memory" not in text
        assert "# Body\n" in text

    def test_no_passport_returns_false(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        text = "---\ntitle: Normal Doc\n---\n# Body\n"
        doc.write_text(text)

        assert remove_passport(doc) is False
        assert doc.read_text() == text

    def test_removes_schema_invalid_passport_when_yaml_is_valid(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  version: 99\n  intent: Newer\n---\n# Body\n")

        assert remove_passport(doc) is True
        assert doc.read_text() == "# Body\n"

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory: [invalid: yaml\n---\n# Body\n")

        with pytest.raises(PassportError, match="malformed YAML"):
            remove_passport(doc)


class TestMutationFrontmatterSafety:
    def _passport(self) -> Passport:
        return Passport(version=1, intent="Safe mutation")

    @pytest.mark.parametrize("yaml_root", ["- item\n", "plain\n", "1\n", "true\n", "null\n", "~\n"])
    def test_write_rejects_non_mapping_roots_byte_identically(self, tmp_path: Path, yaml_root: str) -> None:
        doc = tmp_path / "doc.md"
        original = f"---\n{yaml_root}---\n# Body\n"
        doc.write_text(original)

        with pytest.raises(PassportError, match="frontmatter: must be a mapping"):
            write_passport(doc, self._passport())

        assert doc.read_text() == original
        assert doc.read_text().count("---") == 2

    @pytest.mark.parametrize("yaml_block", ["", "# comment only\n"])
    def test_empty_and_comment_only_frontmatter_remain_writable(self, tmp_path: Path, yaml_block: str) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(f"---\n{yaml_block}---\n# Body\n")

        write_passport(doc, self._passport())

        assert read_passport(doc) is not None
        assert "# Body\n" in doc.read_text()

    @pytest.mark.parametrize(
        "original, error",
        [
            ("\ufeff---\ntitle: BOM\n---\n# Body\n", "leading UTF-8 BOM"),
            ("---\ntitle: EOF\n---", "closing YAML delimiter"),
        ],
    )
    def test_unsupported_delimiter_variants_fail_byte_identically(
        self,
        tmp_path: Path,
        original: str,
        error: str,
    ) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(original)

        with pytest.raises(PassportError, match=error):
            write_passport(doc, self._passport())

        assert doc.read_text() == original

    @pytest.mark.parametrize(
        "original, error",
        [
            ("---\n- forge_memory\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\nplain\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\n1\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\ntrue\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\nnull\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\n~\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("\ufeff---\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Body\n", "leading UTF-8 BOM"),
            ("---\nforge_memory:\n  version: 1\n  intent: Test\n---", "closing YAML delimiter"),
        ],
    )
    def test_remove_rejects_unsafe_frontmatter_byte_identically(
        self,
        tmp_path: Path,
        original: str,
        error: str,
    ) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(original)

        with pytest.raises(PassportError, match=error):
            remove_passport(doc)

        assert doc.read_text() == original


class TestOKFEnvelope:
    def _passport(self, *, intent: str = "Project documentation") -> Passport:
        return Passport(version=1, intent=intent, update=PassportUpdate(strategy="generic"))

    def test_new_passport_gets_exact_envelope_without_deferred_fields(self, tmp_path: Path) -> None:
        doc = tmp_path / "implementation_notes.md"
        doc.write_text("# Implementation Notes\nBody\n")

        added = write_passport(doc, self._passport(), okf_path="docs/implementation_notes.md")

        fm, body = extract_frontmatter(doc.read_text())
        assert fm is not None
        assert added == ("type", "title", "description")
        assert fm["type"] == "Memory Document"
        assert fm["title"] == "Implementation Notes"
        assert fm["description"] == "Project documentation"
        assert "forge_memory" in fm
        assert not {"resource", "tags", "timestamp"} & fm.keys()
        assert body == "# Implementation Notes\nBody\n"

    @pytest.mark.parametrize(
        "body, logical_path, expected",
        [
            (
                "```md\n# Fake\n```\n# Real Heading ###\n",
                "docs/fallback.md",
                "Real Heading",
            ),
            ("~~~\n# Fake\n~~~~\nNo heading\n", "docs/OKF_api-v2.md", "OKF api v2"),
            ("No heading\n", "docs/iOS-guide.md", "iOS guide"),
            ("# First\n# Second\n", "docs/fallback.md", "First"),
            ("# ###\n# Real Heading\n", "docs/fallback.md", "Real Heading"),
        ],
    )
    def test_title_derivation_preserves_authored_case(
        self,
        tmp_path: Path,
        body: str,
        logical_path: str,
        expected: str,
    ) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(body)

        write_passport(doc, self._passport(), okf_path=logical_path)

        fm, _ = extract_frontmatter(doc.read_text())
        assert fm is not None
        assert fm["title"] == expected

    def test_separator_only_stem_omits_optional_title(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("No heading\n")

        added = write_passport(doc, self._passport(), okf_path="docs/---.md")

        fm, _ = extract_frontmatter(doc.read_text())
        assert fm is not None
        assert "title" not in fm
        assert added == ("type", "description")

    def test_description_collapses_intent_whitespace(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# Doc\n")

        write_passport(
            doc,
            self._passport(intent="  Durable\n\tproject   memory  "),
            okf_path="docs/doc.md",
        )

        fm, _ = extract_frontmatter(doc.read_text())
        assert fm is not None
        assert fm["description"] == "Durable project memory"

    @pytest.mark.parametrize("type_yaml", ["null", "''", "'   '", "true", "1", "[]", "{}"])
    def test_invalid_present_type_fails_byte_identically(self, tmp_path: Path, type_yaml: str) -> None:
        doc = tmp_path / "doc.md"
        original = f"---\ntype: {type_yaml}\n---\n# Doc\n"
        doc.write_text(original)

        with pytest.raises(PassportError, match="type: must be a non-empty string"):
            write_passport(doc, self._passport(), okf_path="docs/doc.md")

        assert doc.read_text() == original

    def test_existing_outer_values_are_not_repaired_or_overwritten(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(
            "---\n"
            "type: Custom Concept\n"
            "title:\n"
            "description: 7\n"
            "tags: [custom]\n"
            "timestamp: 2026-07-14\n"
            "custom_key:\n"
            "  nested: true\n"
            "---\n"
            "# Replacement Heading\n"
        )

        write_passport(doc, self._passport(), okf_path="docs/doc.md")

        fm, _ = extract_frontmatter(doc.read_text())
        assert fm is not None
        assert fm["type"] == "Custom Concept"
        assert fm["title"] is None
        assert fm["description"] == 7
        assert fm["tags"] == ["custom"]
        assert str(fm["timestamp"]) == "2026-07-14"
        assert fm["custom_key"] == {"nested": True}

    @pytest.mark.parametrize("logical_path", ["docs/doc.txt", "docs/doc.MD", "docs/index.md", "docs/log.md"])
    def test_invalid_logical_paths_are_rejected(self, tmp_path: Path, logical_path: str) -> None:
        resolved = tmp_path / "doc.md"
        with pytest.raises(PassportError, match="path:"):
            validate_okf_memory_path(logical_path, resolved)

    def test_resolved_reserved_target_is_rejected(self, tmp_path: Path) -> None:
        resolved = tmp_path / "index.md"
        with pytest.raises(PassportError, match="resolved target.*reserved"):
            validate_okf_memory_path("docs/alias.md", resolved)

    def test_suffix_policy_uses_logical_path(self, tmp_path: Path) -> None:
        validate_okf_memory_path("docs/alias.md", tmp_path / "target.txt")
        with pytest.raises(PassportError, match="exact '.md' suffix"):
            validate_okf_memory_path("docs/alias.txt", tmp_path / "target.md")

    def test_prepare_validates_without_writing(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        original = "# Doc\n"
        doc.write_text(original)

        prepared = prepare_passport_write(doc, self._passport(), okf_path="docs/doc.md")

        assert doc.read_text() == original
        assert prepared.added_okf_fields == ("type", "title", "description")
        assert apply_prepared_passport_write(doc, prepared) == prepared.added_okf_fields
        assert "forge_memory" in doc.read_text()


class TestUpgradePassportEnvelope:
    def test_upgrade_preserves_raw_passport_and_is_idempotent(self, tmp_path: Path) -> None:
        doc = tmp_path / "legacy.md"
        doc.write_text(
            "---\n"
            "custom: keep\n"
            "forge_memory:\n"
            "  version: 1\n"
            "  intent: Legacy durable memory\n"
            "  update:\n"
            "    writers: all-sessions\n"
            "    inherit_on_fork: false\n"
            "---\n"
            "# Legacy Notes\n"
        )
        before_fm, _ = extract_frontmatter(doc.read_text())
        assert before_fm is not None
        raw_passport = before_fm["forge_memory"]

        added = upgrade_passport_envelope(doc, logical_path="docs/legacy.md")

        assert added == ("type", "title", "description")
        after_fm, _ = extract_frontmatter(doc.read_text())
        assert after_fm is not None
        assert after_fm["forge_memory"] == raw_passport
        assert after_fm["forge_memory"]["update"] == {
            "writers": "all-sessions",
            "inherit_on_fork": False,
        }
        upgraded = doc.read_bytes()
        assert upgrade_passport_envelope(doc, logical_path="docs/legacy.md") == ()
        assert doc.read_bytes() == upgraded

    def test_upgrade_requires_existing_valid_passport(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("# Doc\n")

        with pytest.raises(PassportError, match="passport not found"):
            upgrade_passport_envelope(doc, logical_path="docs/doc.md")

    def test_upgrade_invalid_type_is_byte_identical(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        original = "---\ntype: []\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Doc\n"
        doc.write_text(original)

        with pytest.raises(PassportError, match="type: must be a non-empty string"):
            upgrade_passport_envelope(doc, logical_path="docs/doc.md")

        assert doc.read_text() == original

    @pytest.mark.parametrize(
        "original, error",
        [
            ("---\n- forge_memory\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\nplain\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\n1\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\ntrue\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\nnull\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("---\n~\n---\n# Body\n", "frontmatter: must be a mapping"),
            ("\ufeff---\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Body\n", "leading UTF-8 BOM"),
            ("---\nforge_memory:\n  version: 1\n  intent: Test\n---", "closing YAML delimiter"),
        ],
    )
    def test_upgrade_rejects_unsafe_frontmatter_byte_identically(
        self,
        tmp_path: Path,
        original: str,
        error: str,
    ) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(original)

        with pytest.raises(PassportError, match=error):
            upgrade_passport_envelope(doc, logical_path="docs/doc.md")

        assert doc.read_text() == original

    @pytest.mark.parametrize("operation", ["write", "upgrade", "remove"])
    def test_successful_mutations_preserve_file_mode(self, tmp_path: Path, operation: str) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("---\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Doc\n")
        doc.chmod(0o644)

        if operation == "write":
            write_passport(doc, Passport(version=1, intent="Changed"))
        elif operation == "upgrade":
            upgrade_passport_envelope(doc, logical_path="docs/doc.md")
        else:
            remove_passport(doc)

        assert stat.S_IMODE(doc.stat().st_mode) == 0o644


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
            strategy="generic",
            update_mode="shadow-only",
            shadow_path=".forge/memory/shadow.md",
        )
        assert p.update.mode == "shadow-only"
        assert p.update.shadow_path == ".forge/memory/shadow.md"

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
            path=".forge/memory/shadow.md",
            strategy="generic",
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
            strategy="generic",
            shadows="docs/impl_notes.md",
        )
        passport = Passport(
            version=1,
            intent="Durable memory",
            update=PassportUpdate(
                strategy="generic",
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
            strategy="generic",
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
            strategy="generic",
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
                strategy="generic",
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
                strategy="generic",
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
                strategy="generic",
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
        assert derive_shadow_path("docs/board/impl_notes.md") == ".forge/memory/shadow_board_impl_notes.md"

    def test_top_level_file_no_prefix(self) -> None:
        assert derive_shadow_path("README.md") == ".forge/memory/shadow_README.md"

    def test_single_parent_dir(self) -> None:
        assert derive_shadow_path("docs/checklist.md") == ".forge/memory/shadow_docs_checklist.md"

    def test_deeply_nested_uses_immediate_parent(self) -> None:
        assert derive_shadow_path("a/b/c/deep/notes.md") == ".forge/memory/shadow_deep_notes.md"


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
