from __future__ import annotations

import stat
from pathlib import Path, PurePosixPath

from forge.install.skill_cache import (
    compiled_skill_cache_dir,
    compiled_skill_digest,
    materialize_compiled_skill,
)
from forge.install.skill_compiler import (
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillRuntime,
)


def _package(content: bytes = b"body\n") -> CompiledSkillPackage:
    return CompiledSkillPackage(
        runtime=SkillRuntime.CODEX,
        name="challenge",
        files=(
            CompiledSkillFile(PurePosixPath("SKILL.md"), content, 0o644),
            CompiledSkillFile(PurePosixPath("scripts/run.sh"), b"#!/bin/sh\n", 0o755),
        ),
    )


def test_cache_path_is_deterministic_and_content_addressed(tmp_path: Path) -> None:
    package = _package()

    first = compiled_skill_cache_dir(package, forge_home=tmp_path)
    second = compiled_skill_cache_dir(package, forge_home=tmp_path)
    changed = compiled_skill_cache_dir(_package(b"changed\n"), forge_home=tmp_path)

    assert first == second
    assert first != changed
    assert first.name == compiled_skill_digest(package)
    assert not first.exists()


def test_materialize_writes_bytes_modes_and_completion_marker(tmp_path: Path) -> None:
    package = _package()

    root = materialize_compiled_skill(package, forge_home=tmp_path)

    assert (root / "SKILL.md").read_bytes() == b"body\n"
    assert (root / "scripts" / "run.sh").read_bytes() == b"#!/bin/sh\n"
    assert stat.S_IMODE((root / "scripts" / "run.sh").stat().st_mode) == 0o755
    assert (root / ".complete").read_text(encoding="utf-8").strip() == compiled_skill_digest(package)


def test_materialize_repairs_tampered_content(tmp_path: Path) -> None:
    package = _package()
    root = materialize_compiled_skill(package, forge_home=tmp_path)
    (root / "SKILL.md").write_bytes(b"tampered")

    repeated = materialize_compiled_skill(package, forge_home=tmp_path)

    assert repeated == root
    assert (root / "SKILL.md").read_bytes() == b"body\n"


def test_materialize_replaces_matching_external_symlink(tmp_path: Path) -> None:
    package = _package()
    root = materialize_compiled_skill(package, forge_home=tmp_path)
    external = tmp_path / "external-skill.md"
    external.write_bytes(b"body\n")
    cached = root / "SKILL.md"
    cached.unlink()
    cached.symlink_to(external)

    repeated = materialize_compiled_skill(package, forge_home=tmp_path)

    assert repeated == root
    assert not cached.is_symlink()
    assert cached.read_bytes() == b"body\n"
