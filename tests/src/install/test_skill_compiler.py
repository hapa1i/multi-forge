from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import pytest
import yaml

from forge.install.skill_compiler import (
    CodexSkillInterface,
    SkillCapability,
    SkillCompilationError,
    SkillManifest,
    SkillRuntime,
    SkillSource,
    SkillSourceFile,
    SkillSourceFormat,
    TokenAllowance,
    compile_skill_for_runtime,
    load_claude_skill_source,
    load_neutral_skill_source,
    load_skill_sources,
)

SKILLS_ROOT = Path(__file__).parents[3] / "src" / "skills"
ALL_RUNTIMES = frozenset({SkillRuntime.CLAUDE_CODE, SkillRuntime.CODEX})
SOURCE_ARTIFACT_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
SOURCE_ARTIFACT_SUFFIXES = frozenset({".pyc", ".pyo"})


def _frontmatter(document: bytes) -> dict[str, object]:
    text = document.decode()
    return yaml.safe_load(text.split("---", 2)[1])


def _is_expected_source_file(package_root: Path, path: Path) -> bool:
    relative = PurePosixPath(path.relative_to(package_root).as_posix())
    return (
        path.is_file()
        and not any(part.startswith(".") for part in relative.parts)
        and not SOURCE_ARTIFACT_DIRS.intersection(relative.parts)
        and relative.suffix not in SOURCE_ARTIFACT_SUFFIXES
    )


def _neutral_source(
    *,
    body: str = "# Demo\n\nFollow the instructions.\n",
    required: frozenset[SkillCapability] = frozenset(),
    files: tuple[SkillSourceFile, ...] = (),
    license: str | None = None,
    compatibility: str | None = None,
    metadata: Mapping[str, str] | None = None,
    allowed_tools: str | None = None,
    allow_implicit_invocation: bool | None = None,
    claude_frontmatter: Mapping[str, Any] | None = None,
    codex_interface: CodexSkillInterface | None = None,
    token_allowances: tuple[TokenAllowance, ...] = (),
    runtime_excluded_files: Mapping[SkillRuntime, frozenset[PurePosixPath]] | None = None,
) -> SkillSource:
    return SkillSource(
        manifest=SkillManifest(
            name="demo-skill",
            description="Demonstrate compiler behavior. Use when testing skill compilation.",
            runtime_eligibility=ALL_RUNTIMES,
            required_capabilities=required,
            license=license,
            compatibility=compatibility,
            metadata=metadata or {},
            allowed_tools=allowed_tools,
            allow_implicit_invocation=allow_implicit_invocation,
            claude_frontmatter=claude_frontmatter or {},
            codex_interface=codex_interface,
            token_allowances=token_allowances,
            runtime_excluded_files=runtime_excluded_files or {},
        ),
        body=body.encode(),
        files=files,
        source_path="neutral/demo-skill",
    )


def test_mixed_sources_preserve_legacy_claude_bridge_byte_and_mode_fidelity() -> None:
    sources = load_skill_sources(SKILLS_ROOT)

    assert [source.manifest.name for source in sources] == sorted(path.name for path in SKILLS_ROOT.iterdir())
    bridge_sources = [source for source in sources if source.source_format == SkillSourceFormat.CLAUDE_BRIDGE]
    assert bridge_sources
    for source in bridge_sources:
        package_root = SKILLS_ROOT / source.manifest.name
        package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
        expected_paths = sorted(
            (
                PurePosixPath(path.relative_to(package_root).as_posix())
                for path in package_root.rglob("*")
                if _is_expected_source_file(package_root, path)
            ),
            key=PurePosixPath.as_posix,
        )
        assert [package_file.path for package_file in package.files] == expected_paths
        for package_file in package.files:
            source_file = package_root / package_file.path
            assert package_file.content == source_file.read_bytes(), package_file.path
            assert package_file.mode == stat.S_IMODE(source_file.stat().st_mode), package_file.path


def test_legacy_claude_bridge_excludes_runtime_build_artifacts(tmp_path: Path) -> None:
    package_root = tmp_path / "legacy-skill"
    (package_root / "resources").mkdir(parents=True)
    (package_root / "scripts" / "__pycache__").mkdir(parents=True)
    (package_root / ".pytest_cache").mkdir()
    (package_root / "SKILL.md").write_text(
        "---\nname: forge:legacy-skill\ndescription: Legacy test skill. Use when testing artifact filters.\n---\n"
        "\n# Legacy\n",
        encoding="utf-8",
    )
    (package_root / "resources" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (package_root / "scripts" / "__pycache__" / "helper.cpython-312.pyc").write_bytes(b"compiled")
    (package_root / "scripts" / "helper.pyo").write_bytes(b"optimized")
    (package_root / ".pytest_cache" / "state").write_text("generated\n", encoding="utf-8")

    source = load_claude_skill_source(package_root)
    package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    assert [package_file.path.as_posix() for package_file in package.files] == [
        "SKILL.md",
        "resources/guide.md",
    ]


@pytest.mark.parametrize(
    ("owned_path", "target_content"),
    [
        (
            "forge-skill.yaml",
            """\
schema_version: 1
name: neutral-skill
description: Neutral test. Use for tests.
runtimes: [codex]
""",
        ),
        ("content.md", "# Neutral\n"),
        ("SKILL.md", "generated migration artifact\n"),
    ],
)
@pytest.mark.parametrize("broken", [False, True])
def test_neutral_loader_rejects_unsafe_compiler_owned_symlinks(
    tmp_path: Path,
    owned_path: str,
    target_content: str,
    *,
    broken: bool,
) -> None:
    package_root = tmp_path / "neutral-skill"
    package_root.mkdir()
    (package_root / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: neutral-skill
description: Neutral test. Use for tests.
runtimes: [codex]
""",
        encoding="utf-8",
    )
    (package_root / "content.md").write_text("# Neutral\n", encoding="utf-8")
    (package_root / "SKILL.md").write_text("generated migration artifact\n", encoding="utf-8")
    external_target = tmp_path / f"external-{owned_path}"
    if not broken:
        external_target.write_text(target_content, encoding="utf-8")
    (package_root / owned_path).unlink()
    (package_root / owned_path).symlink_to(external_target)

    with pytest.raises(ValueError, match="skill source symlink"):
        load_neutral_skill_source(package_root)


def test_claude_loader_rejects_external_skill_document_symlink(tmp_path: Path) -> None:
    package_root = tmp_path / "legacy-skill"
    package_root.mkdir()
    external_document = tmp_path / "external-SKILL.md"
    external_document.write_text(
        "---\nname: forge:legacy-skill\ndescription: Legacy test. Use for tests.\n---\n\n# Legacy\n",
        encoding="utf-8",
    )
    (package_root / "SKILL.md").symlink_to(external_document)

    with pytest.raises(ValueError, match="must target a file inside its package"):
        load_claude_skill_source(package_root)


def test_mixed_loader_preserves_internal_symlink_alias_content() -> None:
    source = next(source for source in load_skill_sources(SKILLS_ROOT) if source.manifest.name == "review")
    assert source.source_format == SkillSourceFormat.NEUTRAL

    package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    assert package.file("resources/code.md").content == package.file("resources/code-anthropic.md").content


def test_compilation_is_deterministic_and_runtime_names_are_explicit() -> None:
    source = _neutral_source(
        files=(
            SkillSourceFile(PurePosixPath("scripts/run.sh"), b"#!/bin/sh\nexit 0\n", mode=0o755),
            SkillSourceFile(PurePosixPath("references/guide.md"), b"# Guide\n"),
        ),
        license="Apache-2.0",
        compatibility="Requires Forge CLI.",
        metadata={"author": "forge", "version": "1"},
        allowed_tools="Read Bash(forge:*)",
    )

    claude_first = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    claude_second = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex_first = compile_skill_for_runtime(source, SkillRuntime.CODEX)
    codex_second = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert claude_first == claude_second
    assert codex_first == codex_second
    assert _frontmatter(claude_first.file("SKILL.md").content)["name"] == "forge:demo-skill"
    assert _frontmatter(codex_first.file("SKILL.md").content)["name"] == "demo-skill"
    assert codex_first.file("scripts/run.sh").mode == 0o755
    assert tuple(item.path for item in codex_first.files) == tuple(
        sorted((item.path for item in codex_first.files), key=PurePosixPath.as_posix)
    )


def test_claude_capability_placeholder_is_typed_and_rendered() -> None:
    source = _neutral_source(
        body="Read {{forge:task_arguments}} and run {{forge:forge_cli}} status.\n",
        required=frozenset({SkillCapability.TASK_ARGUMENTS, SkillCapability.FORGE_CLI}),
    )

    package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    body = package.file("SKILL.md").content.decode()
    assert "Read $ARGUMENTS and run forge status." in body
    assert "{{forge:" not in body


def test_packaged_script_path_uses_runtime_specific_loaded_skill_root_binding() -> None:
    source = _neutral_source(
        body="{{forge:packaged_script:scripts/check.sh}}\n",
        required=frozenset({SkillCapability.PACKAGED_SCRIPT}),
        files=(SkillSourceFile(PurePosixPath("scripts/check.sh"), b"#!/bin/sh\n", mode=0o755),),
    )

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert (
        'FORGE_SKILL_RUNTIME=claude_code bash "${CLAUDE_SKILL_DIR}/scripts/check.sh"'
        in claude.file("SKILL.md").content.decode()
    )
    codex_body = codex.file("SKILL.md").content.decode()
    assert "`scripts/check.sh`" in codex_body
    assert "directory containing this SKILL.md" in codex_body
    assert "execute the resulting absolute path" in codex_body
    assert "`FORGE_SKILL_RUNTIME=codex`" in codex_body


@pytest.mark.parametrize("mode", [0o644, 0o001, 0o100, 0o400])
def test_packaged_script_path_requires_owner_read_and_execute(mode: int) -> None:
    script_path = PurePosixPath("scripts/check.sh")
    source = _neutral_source(
        body="{{forge:packaged_script:scripts/check.sh}}\n",
        required=frozenset({SkillCapability.PACKAGED_SCRIPT}),
        files=(SkillSourceFile(script_path, b"#!/bin/sh\n", mode=mode),),
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CODEX)

    diagnostic = next(
        item for item in exc_info.value.diagnostics if item.rule == "template.non-executable-package-path"
    )
    assert diagnostic.path == script_path
    assert diagnostic.capability == SkillCapability.PACKAGED_SCRIPT
    assert "0o755" in diagnostic.recovery


def test_resource_path_uses_claude_absolute_and_codex_package_relative_binding() -> None:
    source = _neutral_source(
        body="{{forge:resource_loading:resources/guide.md}}\n",
        required=frozenset({SkillCapability.RESOURCE_LOADING}),
        files=(SkillSourceFile(PurePosixPath("resources/guide.md"), b"# Guide\n"),),
    )

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert "${CLAUDE_SKILL_DIR}/resources/guide.md" in claude.file("SKILL.md").content.decode()
    codex_body = codex.file("SKILL.md").content.decode()
    assert "Read `resources/guide.md`" in codex_body
    assert "directory containing this SKILL.md" in codex_body


def test_codex_task_arguments_bind_to_explicit_or_implicit_activation_text() -> None:
    source = _neutral_source(
        body="Use {{forge:task_arguments}}.\n",
        required=frozenset({SkillCapability.TASK_ARGUMENTS}),
    )

    package = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert (
        "Use the task text supplied when this skill was invoked or selected."
        in package.file("SKILL.md").content.decode()
    )


def test_model_family_binding_preserves_claude_pre_step_and_is_codex_native() -> None:
    source = _neutral_source(
        body="{{forge:model_family}}\n",
        required=frozenset({SkillCapability.MODEL_FAMILY}),
    )

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    claude_body = claude.file("SKILL.md").content.decode()
    assert "!`forge session show --field model_family 2>/dev/null || true`" in claude_body
    assert "!`forge session show --field main_model 2>/dev/null || true`" in claude_body
    codex_body = codex.file("SKILL.md").content.decode()
    assert "`forge session show --field model_family`" in codex_body
    assert "`forge session show --field main_model`" in codex_body
    assert "!`" not in codex_body


def test_exploration_binding_preserves_claude_tool_and_is_codex_native() -> None:
    source = _neutral_source(
        body="Use {{forge:exploration}} before analysis.\n",
        required=frozenset({SkillCapability.EXPLORATION}),
    )

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert 'Use the `Agent` tool with `subagent_type: "Explore"`' in claude.file("SKILL.md").content.decode()
    codex_body = codex.file("SKILL.md").content.decode()
    assert "runtime-native repository search and file reads" in codex_body
    assert "parallel workers" in codex_body
    assert "Agent" not in codex_body
    assert "Explore" not in codex_body
    assert "subagent_type" not in codex_body


def test_neutral_reference_token_allowance_never_weakens_shared_source_gate() -> None:
    reference_path = PurePosixPath("references/skills-writing-guide.md")
    reference = SkillSourceFile(reference_path, b"Document the literal $ARGUMENTS token.\n")
    exact = TokenAllowance(SkillRuntime.CODEX, reference_path, "token.claude-arguments")
    source = _neutral_source(files=(reference,), token_allowances=(exact,))

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert any(item.rule == "neutral.token.claude-arguments" for item in exc_info.value.diagnostics)


def test_runtime_specific_document_is_preserved_in_claude_and_absent_from_codex() -> None:
    reference_path = PurePosixPath("references/skills-writing-guide.md")
    reference = SkillSourceFile(reference_path, b"Document Claude's literal $ARGUMENTS token.\n")
    source = _neutral_source(
        files=(reference,),
        runtime_excluded_files={SkillRuntime.CODEX: frozenset({reference_path})},
    )

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert claude.file(reference_path).content == reference.content
    with pytest.raises(KeyError):
        codex.file(reference_path)


def test_document_cannot_be_excluded_from_every_eligible_runtime() -> None:
    reference_path = PurePosixPath("references/runtime-note.md")
    source = _neutral_source(
        files=(SkillSourceFile(reference_path, b"# Runtime note\n"),),
        runtime_excluded_files={
            SkillRuntime.CLAUDE_CODE: frozenset({reference_path}),
            SkillRuntime.CODEX: frozenset({reference_path}),
        },
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CODEX)

    diagnostic = next(item for item in exc_info.value.diagnostics if item.rule == "source.runtime-exclusion-all")
    assert diagnostic.path == reference_path


@pytest.mark.parametrize(("template", "mode"), [(True, 0o644), (False, 0o755)])
def test_runtime_exclusions_reject_behavioral_source_files(template: bool, mode: int) -> None:
    reference_path = PurePosixPath("references/runtime-note.md")
    source = _neutral_source(
        files=(SkillSourceFile(reference_path, b"# Runtime note\n", mode=mode, template=template),),
        runtime_excluded_files={SkillRuntime.CODEX: frozenset({reference_path})},
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    diagnostic = next(item for item in exc_info.value.diagnostics if item.rule == "source.runtime-exclusion-behavioral")
    assert diagnostic.path == reference_path
    assert "non-templated, non-executable" in diagnostic.recovery


@pytest.mark.parametrize(("template", "mode"), [(True, 0o644), (False, 0o755)])
def test_neutral_loader_rejects_behavioral_runtime_exclusions(
    tmp_path: Path,
    *,
    template: bool,
    mode: int,
) -> None:
    package_root = tmp_path / "neutral-skill"
    references = package_root / "references"
    references.mkdir(parents=True)
    template_line = "template_files: [references/runtime-note.md]\n" if template else ""
    (package_root / "forge-skill.yaml").write_text(
        "schema_version: 1\n"
        "name: neutral-skill\n"
        "description: Neutral test. Use for tests.\n"
        "runtimes: [claude_code, codex]\n"
        f"{template_line}"
        "runtime_excluded_files:\n"
        "  codex: [references/runtime-note.md]\n",
        encoding="utf-8",
    )
    (package_root / "content.md").write_text("# Neutral\n", encoding="utf-8")
    runtime_note = references / "runtime-note.md"
    runtime_note.write_text("# Runtime note\n", encoding="utf-8")
    runtime_note.chmod(mode)

    with pytest.raises(ValueError, match="non-templated, non-executable"):
        load_neutral_skill_source(package_root)


def test_mixed_loader_discovers_neutral_and_legacy_sources(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy-skill"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text(
        "---\nname: forge:legacy-skill\ndescription: Legacy test skill. Use when testing discovery.\n---\n\n# Legacy\n",
        encoding="utf-8",
    )

    neutral = tmp_path / "neutral-skill"
    (neutral / "scripts").mkdir(parents=True)
    (neutral / "references").mkdir()
    (neutral / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: neutral-skill
description: Neutral test skill. Use when testing discovery.
runtimes: [claude_code, codex]
capabilities: [forge_cli, packaged_script]
template_files: [references/template.md]
runtime_excluded_files:
  codex: [references/claude-only.md]
codex_interface:
  display_name: Neutral Skill
""",
        encoding="utf-8",
    )
    (neutral / "content.md").write_text(
        "# Neutral\n\n{{forge:packaged_script:scripts/check.sh}}\n",
        encoding="utf-8",
    )
    script = neutral / "scripts" / "check.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    (neutral / "references" / "template.md").write_text("Run {{forge:forge_cli}} status.\n", encoding="utf-8")
    (neutral / "references" / "claude-only.md").write_text("Literal $ARGUMENTS documentation.\n", encoding="utf-8")
    (neutral / "SKILL.md").write_text("generated migration artifact\n", encoding="utf-8")

    sources = load_skill_sources(tmp_path)

    assert [source.manifest.name for source in sources] == [
        "legacy-skill",
        "neutral-skill",
    ]
    assert [source.source_format for source in sources] == [
        SkillSourceFormat.CLAUDE_BRIDGE,
        SkillSourceFormat.NEUTRAL,
    ]
    neutral_source = sources[1]
    assert {source_file.path for source_file in neutral_source.files} == {
        PurePosixPath("references/template.md"),
        PurePosixPath("references/claude-only.md"),
        PurePosixPath("scripts/check.sh"),
    }
    assert next(item for item in neutral_source.files if item.path == PurePosixPath("scripts/check.sh")).mode == 0o755
    package = compile_skill_for_runtime(neutral_source, SkillRuntime.CODEX)
    assert PurePosixPath("references/claude-only.md") not in {item.path for item in package.files}
    assert "Run forge status." in package.file("references/template.md").content.decode()
    assert "directory containing this SKILL.md" in package.file("SKILL.md").content.decode()
    claude_package = compile_skill_for_runtime(neutral_source, SkillRuntime.CLAUDE_CODE)
    assert claude_package.file("references/claude-only.md").content == b"Literal $ARGUMENTS documentation.\n"


@pytest.mark.parametrize(
    "manifest_patch",
    [
        "unknown_field: true\n",
        "runtimes: [unknown]\n",
        "capabilities: [unknown]\n",
        "template_files: [references/missing.md]\n",
        "runtime_excluded_files: {codex: [content.md]}\n",
        "runtime_excluded_files: {codex: [references/missing.md]}\n",
        "runtime_excluded_files: {codex: [scripts/check.sh]}\n",
    ],
)
def test_neutral_loader_rejects_invalid_manifest_contract(tmp_path: Path, manifest_patch: str) -> None:
    package_root = tmp_path / "neutral-skill"
    package_root.mkdir()
    base = """\
schema_version: 1
name: neutral-skill
description: Neutral test skill. Use when testing loading.
runtimes: [codex]
"""
    (package_root / "forge-skill.yaml").write_text(base + manifest_patch, encoding="utf-8")
    (package_root / "content.md").write_text("# Neutral\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_neutral_skill_source(package_root)


@pytest.mark.parametrize(
    ("manifest_field", "manifest_value", "claude_field", "claude_value"),
    [
        ("license", "Apache-2.0", "license", "MIT"),
        ("compatibility", "Requires Forge.", "compatibility", "Requires another tool."),
        ("metadata", {"author": "forge"}, "metadata", {"author": "other"}),
        ("allowed_tools", "Read", "allowed-tools", "Bash"),
        ("allow_implicit_invocation", True, "disable-model-invocation", True),
        ("license", None, "license", "MIT"),
        ("allow_implicit_invocation", None, "disable-model-invocation", True),
    ],
)
def test_neutral_loader_rejects_conflicting_typed_and_claude_frontmatter(
    tmp_path: Path,
    manifest_field: str,
    manifest_value: object,
    claude_field: str,
    claude_value: object,
) -> None:
    package_root = tmp_path / "neutral-skill"
    package_root.mkdir()
    manifest = {
        "schema_version": 1,
        "name": "neutral-skill",
        "description": "Neutral test skill. Use when testing loading.",
        "runtimes": ["claude_code", "codex"],
        manifest_field: manifest_value,
        "claude_frontmatter": {claude_field: claude_value},
    }
    (package_root / "forge-skill.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    (package_root / "content.md").write_text("# Neutral\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"conflicting declarations for {manifest_field}"):
        load_neutral_skill_source(package_root)


def test_neutral_loader_accepts_equivalent_invocation_policy_declarations(tmp_path: Path) -> None:
    package_root = tmp_path / "neutral-skill"
    package_root.mkdir()
    (package_root / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: neutral-skill
description: Neutral test skill. Use when testing loading.
runtimes: [claude_code, codex]
capabilities: [invocation_policy]
allow_implicit_invocation: true
claude_frontmatter:
  disable-model-invocation: false
""",
        encoding="utf-8",
    )
    (package_root / "content.md").write_text("# Neutral\n", encoding="utf-8")

    source = load_neutral_skill_source(package_root)

    package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    assert _frontmatter(package.file("SKILL.md").content)["disable-model-invocation"] is False


@pytest.mark.parametrize(
    ("placeholder", "rule"),
    [
        ("{{forge:packaged_script}}", "template.missing-path-argument"),
        ("{{forge:packaged_script:}}", "template.missing-path-argument"),
        ("{{forge:packaged_script:/tmp/check.sh}}", "template.invalid-path-argument"),
        ("{{forge:packaged_script:../check.sh}}", "template.invalid-path-argument"),
        ("{{forge:packaged_script:C:/check.sh}}", "template.invalid-path-argument"),
        (
            "{{forge:packaged_script:scripts/missing.sh}}",
            "template.missing-package-path",
        ),
        ("{{forge:task_arguments:unexpected}}", "template.unexpected-argument"),
    ],
)
def test_path_placeholder_rejects_missing_unsafe_or_unexpected_arguments(placeholder: str, rule: str) -> None:
    source = _neutral_source(
        body=f"{placeholder}\n",
        required=frozenset({SkillCapability.PACKAGED_SCRIPT, SkillCapability.TASK_ARGUMENTS}),
        files=(SkillSourceFile(PurePosixPath("scripts/check.sh"), b"#!/bin/sh\n", mode=0o755),),
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CODEX)

    diagnostic = next(item for item in exc_info.value.diagnostics if item.rule == rule)
    assert diagnostic.path == PurePosixPath("SKILL.md")
    assert diagnostic.source_path == "neutral/demo-skill"
    assert diagnostic.recovery


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        ("Use {{forge:not_a_capability}}.\n", "template.unknown-capability"),
        ("Use {{forge:forge_cli}}.\n", "template.undeclared-capability"),
        ("Use {{forge:forge_cli.\n", "template.malformed-placeholder"),
    ],
)
def test_placeholder_errors_are_actionable(body: str, rule: str) -> None:
    source = _neutral_source(body=body)

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    diagnostic = next(item for item in exc_info.value.diagnostics if item.rule == rule)
    assert diagnostic.path == PurePosixPath("SKILL.md")
    assert diagnostic.recovery


def test_runtime_eligibility_is_an_explicit_safe_gate() -> None:
    source = SkillSource(
        manifest=SkillManifest(name="demo-skill", description="Demo. Use for tests."),
        body=b"# Demo\n",
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CODEX)

    assert exc_info.value.diagnostics[0].rule == "source.runtime-eligibility"


def test_invocation_policy_capability_requires_an_explicit_portable_value() -> None:
    source = _neutral_source(required=frozenset({SkillCapability.INVOCATION_POLICY}))

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    assert any(item.rule == "source.invocation-policy-value" for item in exc_info.value.diagnostics)


def test_codex_bridge_rejects_raw_claude_tokens_after_explicit_opt_in() -> None:
    bridge = next(source for source in load_skill_sources(SKILLS_ROOT) if source.manifest.name == "panel")
    assert bridge.source_format == SkillSourceFormat.CLAUDE_BRIDGE
    bridge = replace(
        bridge,
        manifest=replace(bridge.manifest, runtime_eligibility=ALL_RUNTIMES),
    )

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(bridge, SkillRuntime.CODEX)

    rules = {diagnostic.rule for diagnostic in exc_info.value.diagnostics}
    assert "token.claude-arguments" in rules
    assert "token.claude-command-name" in rules
    assert all(diagnostic.runtime == SkillRuntime.CODEX for diagnostic in exc_info.value.diagnostics)


def test_neutral_source_rejects_raw_runtime_token_even_for_claude_output() -> None:
    source = _neutral_source(body="Read $ARGUMENTS directly.\n")

    with pytest.raises(SkillCompilationError) as exc_info:
        compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    diagnostic = next(item for item in exc_info.value.diagnostics if item.rule == "neutral.token.claude-arguments")
    assert diagnostic.path == PurePosixPath("SKILL.md")
    assert "{{forge:task_arguments}}" in diagnostic.recovery


def test_codex_emits_spec_frontmatter_and_typed_openai_metadata() -> None:
    source = _neutral_source(
        required=frozenset({SkillCapability.INVOCATION_POLICY}),
        allow_implicit_invocation=False,
        claude_frontmatter={"argument-hint": "[target]", "context": "fork"},
        codex_interface=CodexSkillInterface(
            display_name="Demo Skill",
            short_description="Run a compiler demonstration",
            icon_small="./assets/icon.svg",
            brand_color="#3B82F6",
        ),
        files=(SkillSourceFile(PurePosixPath("assets/icon.svg"), b"<svg/>\n"),),
    )

    package = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    frontmatter = _frontmatter(package.file("SKILL.md").content)
    assert set(frontmatter) == {"name", "description"}
    openai = yaml.safe_load(package.file("agents/openai.yaml").content)
    assert openai["policy"] == {"allow_implicit_invocation": False}
    assert openai["interface"]["display_name"] == "Demo Skill"
    assert package.file("agents/openai.yaml").mode == 0o644


def test_claude_emission_uses_typed_manifest_fields_as_authority() -> None:
    source = _neutral_source(
        required=frozenset({SkillCapability.INVOCATION_POLICY}),
        license="Apache-2.0",
        compatibility="Requires Forge CLI.",
        metadata={"author": "forge"},
        allowed_tools="Read",
        allow_implicit_invocation=True,
        claude_frontmatter={
            "license": "MIT",
            "compatibility": "Requires another tool.",
            "metadata": {"author": "other"},
            "allowed-tools": "Bash",
            "disable-model-invocation": True,
        },
    )

    package = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)

    frontmatter = _frontmatter(package.file("SKILL.md").content)
    assert frontmatter["license"] == "Apache-2.0"
    assert frontmatter["compatibility"] == "Requires Forge CLI."
    assert frontmatter["metadata"] == {"author": "forge"}
    assert frontmatter["allowed-tools"] == "Read"
    assert frontmatter["disable-model-invocation"] is False


def test_model_family_resources_remain_shared_across_runtime_outputs() -> None:
    files = tuple(
        SkillSourceFile(PurePosixPath(f"resources/code-{family}.md"), f"# {family}\n".encode())
        for family in ("anthropic", "gemini", "openai")
    )
    source = _neutral_source(files=files)

    claude = compile_skill_for_runtime(source, SkillRuntime.CLAUDE_CODE)
    codex = compile_skill_for_runtime(source, SkillRuntime.CODEX)

    for source_file in files:
        assert claude.file(source_file.path).content == source_file.content
        assert codex.file(source_file.path).content == source_file.content
    for package in (claude, codex):
        emitted_resource_stems = {
            package_file.path.stem
            for package_file in package.files
            if package_file.path.parent == PurePosixPath("resources")
        }
        assert emitted_resource_stems == {"code-anthropic", "code-gemini", "code-openai"}
