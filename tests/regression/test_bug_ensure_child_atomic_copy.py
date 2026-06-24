"""Regression: ensure_child must copy generated.md -> children/<child>.md atomically.

Bug (audit P3/#2, low): ensure_child used shutil.copyfile(source, target), which opens the FINAL
path with O_WRONLY|O_TRUNC and streams into it. A concurrent reader -- `forge session transfer show/diff`,
or the resume-time GC byte-compare that decides whether a colliding auto-name owns its snapshot --
could observe children/<child>.md at 0 or partial bytes during first creation, corrupting the
diff/compare. The torn window also threatens the generated==child byte-identity invariant the
auto-name retry (test_bug_resume_autoname_context_retry) relies on.

Fix: ensure_child now delegates to forge.core.state.io.atomic_write_text (tempfile + os.replace), so
the destination is created via an atomic rename -- never observed truncated -- and the utf-8 round
trip stays byte-identical to generated.md.

Affected: src/forge/session/prev_sessions.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import forge.session.prev_sessions as ps
from forge.session.prev_sessions import child_path, ensure_child, generated_path

pytestmark = pytest.mark.regression


def test_ensure_child_copy_delegates_to_atomic_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_child must route the copy through atomic_write_text, not a truncate-and-stream copy.

    Spying the delegation is deterministic and still fails loudly if anyone reintroduces
    shutil.copyfile (zero recorded calls). It also pins the generated==child byte-identity invariant.
    """
    forge_root = tmp_path
    parent, child = "parent", "child"
    gen = generated_path(forge_root, parent)
    gen.parent.mkdir(parents=True, exist_ok=True)
    content = "FULL GENERATED CONTEXT\n" * 500  # large enough that a streaming copy would tear visibly
    gen.write_text(content, encoding="utf-8")

    calls: list[tuple[Path, str]] = []
    real_atomic = ps.atomic_write_text

    def spy(path: Path, text: str, **kwargs: object) -> None:
        calls.append((Path(path), text))
        real_atomic(path, text, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ps, "atomic_write_text", spy)

    target = ensure_child(forge_root, parent, child)

    assert calls == [(target, content)], "ensure_child must delegate the copy to atomic_write_text exactly once"
    assert target == child_path(forge_root, parent, child)
    assert target.read_text(encoding="utf-8") == content, "child snapshot must be byte-identical to generated.md"


def test_ensure_child_leaves_no_temp_litter(tmp_path: Path) -> None:
    """The atomic write must not leave its sibling tempfile (.<stem>.*.tmp) behind on success."""
    forge_root = tmp_path
    gen = generated_path(forge_root, "parent")
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text("CONTEXT\n", encoding="utf-8")

    target = ensure_child(forge_root, "parent", "child")

    leftovers = [p.name for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == [], f"atomic copy left temp litter: {leftovers}"


def test_ensure_child_is_idempotent_and_does_not_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing (possibly user-curated) child snapshot is returned untouched -- no second write."""
    forge_root = tmp_path
    gen = generated_path(forge_root, "parent")
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text("GENERATED\n", encoding="utf-8")

    target = ensure_child(forge_root, "parent", "child")
    target.write_text("USER-CURATED\n", encoding="utf-8")  # diverge from generated.md

    calls: list[Path] = []
    monkeypatch.setattr(ps, "atomic_write_text", lambda path, _text, **_kw: calls.append(Path(path)))

    again = ensure_child(forge_root, "parent", "child")

    assert again == target
    assert calls == [], "ensure_child must not rewrite an existing snapshot"
    assert target.read_text(encoding="utf-8") == "USER-CURATED\n", "user curation must be preserved"
