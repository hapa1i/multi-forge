"""Regression for passport mutation choosing a different YAML delimiter than reads.

Bug ID: okf-passport-frontmatter-delimiter-selection
Root cause: the mutation regex accepted a zero-line YAML block while the
permissive read regex required at least one line. With an immediate YAML
document-start marker and a later closing delimiter, reads found the passport
but mutations inspected an empty mapping and could prepend a second block.
Affected file: src/forge/session/passport.py
Fix: mutation parsing prefers the permissive reader's delimiter span while
retaining a fallback for a genuinely empty zero-line block.
"""

from pathlib import Path

import pytest

from forge.session.passport import Passport, read_passport, write_passport

pytestmark = pytest.mark.regression


def test_passport_write_uses_the_frontmatter_block_selected_by_reads(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "---\n"
        "---\n"
        "forge_memory:\n"
        "  version: 1\n"
        "  intent: Legacy\n"
        "  update:\n"
        "    strategy: generic\n"
        "---\n"
        "# Body\n"
    )
    assert read_passport(doc) is not None

    write_passport(doc, Passport(version=1, intent="Replacement"))

    passport = read_passport(doc)
    assert passport is not None
    assert passport.intent == "Replacement"
    assert doc.read_text().count("---") == 2
    assert "intent: Legacy" not in doc.read_text()
