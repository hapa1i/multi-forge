"""Regression for ``okf_compatible_memory_passports`` AT-08.

Root cause: passport mutation treated a non-mapping YAML root as absent frontmatter and prepended a new block while
leaving the original metadata block in place. Affected file: ``src/forge/session/passport.py``.
"""

from pathlib import Path

import pytest

from forge.session.exceptions import PassportError
from forge.session.passport import Passport, write_passport

pytestmark = pytest.mark.regression


def test_nonmapping_frontmatter_write_fails_without_creating_second_block(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "third-party.md"
    original = "---\n- third-party\n- metadata\n---\n# Body\n"
    doc.write_text(original)

    with pytest.raises(PassportError, match="frontmatter: must be a mapping"):
        write_passport(doc, Passport(version=1, intent="Project documentation"))

    assert doc.read_text() == original
    assert doc.read_text().count("---") == 2
