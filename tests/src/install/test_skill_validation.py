from __future__ import annotations

from pathlib import PurePosixPath

import pytest
import yaml

from forge.install.skill_compiler import (
    FORGE_PACKAGE_SENTINEL,
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillRuntime,
    TokenAllowance,
)
from forge.install.skill_validation import validate_compiled_skill


def _skill_document(name: str = "demo-skill", **extra: object) -> bytes:
    frontmatter: dict[str, object] = {
        "name": name,
        "description": "Demonstrate validation. Use when testing skill packages.",
        **extra,
    }
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n# Demo\n".encode()


def _package(
    *files: CompiledSkillFile,
    runtime: SkillRuntime = SkillRuntime.CODEX,
    name: str = "demo-skill",
    allowances: tuple[TokenAllowance, ...] = (),
) -> CompiledSkillPackage:
    package_files = files or (CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(name), 0o644),)
    return CompiledSkillPackage(
        runtime=runtime,
        name=name,
        files=package_files,
        token_allowances=allowances,
    )


@pytest.mark.parametrize("runtime", [SkillRuntime.CLAUDE_CODE, SkillRuntime.CODEX])
def test_whole_tree_validator_accepts_package_sentinel(runtime: SkillRuntime) -> None:
    frontmatter_name = "forge:demo-skill" if runtime == SkillRuntime.CLAUDE_CODE else "demo-skill"
    package = _package(
        CompiledSkillFile(
            PurePosixPath(FORGE_PACKAGE_SENTINEL),
            b'{"files":[],"producer":"multi-forge","runtime":"codex","schema_version":1,"skill":"demo-skill"}\n',
            0o644,
        ),
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(frontmatter_name), 0o644),
        runtime=runtime,
    )

    assert validate_compiled_skill(package) == ()


def test_whole_tree_token_scan_reports_nested_path_runtime_rule_and_recovery() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(
            PurePosixPath("references/nested.md"),
            b'Run bash "${CLAUDE_SKILL_DIR}/scripts/check.sh".\n',
            0o644,
        ),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == "token.claude-skill-dir")
    assert diagnostic.runtime == SkillRuntime.CODEX
    assert diagnostic.skill == "demo-skill"
    assert diagnostic.path == PurePosixPath("references/nested.md")
    assert "packaged_script" in diagnostic.recovery


@pytest.mark.parametrize(
    "skill_dir",
    [
        "${CLAUDE_SKILL_DIR}",
        "$CLAUDE_SKILL_DIR",
        "${CLAUDE_SKILL_DIR:-/tmp/fallback}",
        "${CLAUDE_SKILL_DIR#*/}",
    ],
)
def test_codex_token_scan_rejects_both_claude_skill_dir_forms(skill_dir: str) -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(
            PurePosixPath("scripts/check.sh"),
            f'echo "{skill_dir}/data"\n'.encode(),
            0o755,
        ),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == "token.claude-skill-dir")
    assert diagnostic.path == PurePosixPath("scripts/check.sh")


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("$HOME/.claude/settings.json\n", "token.claude-home-path"),
        ("Tool: Agent\n", "token.claude-agent-tool"),
        ("Call `Read` with one argument.\n", "token.claude-read-tool"),
        ("A PreToolUse hook strips parameters.\n", "token.claude-hook-contract"),
        (
            "Strip the Claude Code file reference syntax.\n",
            "token.claude-file-reference",
        ),
        (
            "Use Claude Code default when the model is missing.\n",
            "token.claude-default-model",
        ),
    ],
)
def test_whole_tree_scan_covers_operational_claude_couplings(text: str, rule: str) -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("nested/content.txt"), text.encode(), 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == rule)
    assert diagnostic.path == PurePosixPath("nested/content.txt")
    assert diagnostic.recovery


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        (b"Literal compatibility example: $ARGUMENTS\n", "token.claude-arguments"),
        (b"Literal ${CLAUDE_SKILL_DIR} example.\n", "token.claude-skill-dir"),
        (b'Literal subagent_type: "Explore" example.\n', "token.claude-subagent-type"),
    ],
)
def test_codex_falsifier_token_allowance_never_suppresses_gate(content: bytes, rule: str) -> None:
    path = PurePosixPath("references/compatibility.md")
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(path, content, 0o644),
        allowances=(TokenAllowance(SkillRuntime.CODEX, path, rule),),
    )

    diagnostics = validate_compiled_skill(package)

    rules = {item.rule for item in diagnostics}
    assert rule in rules
    assert "allowance.codex-token-gate" in rules


def test_claude_allowance_cannot_suppress_unresolved_placeholder() -> None:
    path = PurePosixPath("references/unresolved.md")
    rule = "token.unresolved-placeholder"
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document("forge:demo-skill"), 0o644),
        CompiledSkillFile(path, b"Use {{forge:task_arguments}}.\n", 0o644),
        runtime=SkillRuntime.CLAUDE_CODE,
        allowances=(TokenAllowance(SkillRuntime.CLAUDE_CODE, path, rule),),
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert rule in rules
    assert "allowance.token-gate" in rules


def test_codex_frontmatter_uses_closed_agent_skills_contract() -> None:
    document = _skill_document(
        "Bad--Name",
        metadata={"version": 1},
        **{"allowed-tools": "Read, Bash", "argument-hint": "[target]"},
    )
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        name="bad--name",
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "codex.frontmatter-fields",
        "codex.name-directory",
        "codex.name-format",
        "codex.metadata",
        "codex.allowed-tools",
    } <= rules


def test_codex_field_limits_and_types_are_validated() -> None:
    document = _skill_document(
        description="x" * 1025,
        compatibility="",
        license=3,
    )
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {"codex.description", "codex.compatibility", "codex.license"} <= rules


def test_non_string_unknown_frontmatter_key_is_reported_without_validator_crash() -> None:
    frontmatter: dict[object, object] = {
        "name": "demo-skill",
        "description": "Demo validation. Use for tests.",
        1: "invalid",
        "unknown": True,
    }
    document = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n# Demo\n".encode()
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert "codex.frontmatter-fields" in rules


def test_claude_owned_frontmatter_fields_validate_types_and_enums() -> None:
    document = _skill_document(
        "forge:demo-skill",
        compatibility="x" * 501,
        license=1,
        metadata=[],
        **{
            "agent": False,
            "allowed-tools": ["Read"],
            "argument-hint": False,
            "context": "inline",
            "disable-model-invocation": "false",
            "effort": "extreme",
            "hooks": [],
            "model": False,
            "user-invocable": "true",
        },
    )
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        runtime=SkillRuntime.CLAUDE_CODE,
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "claude.agent",
        "claude.allowed-tools",
        "claude.argument-hint",
        "claude.compatibility",
        "claude.context",
        "claude.disable-model-invocation",
        "claude.effort",
        "claude.hooks",
        "claude.license",
        "claude.metadata",
        "claude.model",
        "claude.user-invocable",
    } <= rules


def test_claude_owned_frontmatter_accepts_documented_values() -> None:
    document = _skill_document(
        "forge:demo-skill",
        **{
            "allowed-tools": "Read, Bash(git:*)",
            "argument-hint": "[target]",
            "context": "fork",
            "disable-model-invocation": True,
            "effort": "max",
            "hooks": {},
            "user-invocable": False,
        },
    )
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        runtime=SkillRuntime.CLAUDE_CODE,
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.rule.startswith("claude.") for item in diagnostics)


def test_claude_owned_frontmatter_rejects_explicit_nulls() -> None:
    document = _skill_document(
        "forge:demo-skill",
        **{
            "allowed-tools": None,
            "argument-hint": None,
            "disable-model-invocation": None,
            "effort": None,
        },
    )
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        runtime=SkillRuntime.CLAUDE_CODE,
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "claude.allowed-tools",
        "claude.argument-hint",
        "claude.disable-model-invocation",
        "claude.effort",
    } <= rules


def test_claude_effort_type_validation_does_not_assume_a_hashable_value() -> None:
    document = _skill_document("forge:demo-skill", effort=["high"])
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        runtime=SkillRuntime.CLAUDE_CODE,
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert "claude.effort" in rules


def test_references_must_resolve_without_escaping_package() -> None:
    document = _skill_document() + b"[escape](../secret.md)\n[missing](references/missing.md)\n"
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert "reference.escape" in rules
    assert "reference.missing" in rules


def test_dynamic_reference_suffix_cannot_hide_static_absolute_or_escape_prefix() -> None:
    document = _skill_document() + (
        b"[relative](references/$DOCUMENT.md)\n" b"[escape](../$HOME/secret.md)\n" b"[absolute](/tmp/$USER/secret.md)\n"
    )
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    diagnostics = [item for item in validate_compiled_skill(package) if item.rule.startswith("reference.")]

    assert {item.rule for item in diagnostics} == {"reference.absolute", "reference.escape"}
    assert any("../$HOME/secret.md" in item.message for item in diagnostics)
    assert any("/tmp/$USER/secret.md" in item.message for item in diagnostics)


def test_reference_definitions_and_nested_labels_are_contained() -> None:
    document = _skill_document() + (
        b"[nested [label]](../inline-secret.md)\n"
        b"[escape]: ../definition-secret.md\n"
        b"[multiline-escape]:\n"
        b"  ../multiline-secret.md\n"
        b"[missing]: <references/missing.md> 'optional title'\n"
    )
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    diagnostics = validate_compiled_skill(package)

    escape_messages = [item.message for item in diagnostics if item.rule == "reference.escape"]
    assert any("inline-secret.md" in message for message in escape_messages)
    assert any("definition-secret.md" in message for message in escape_messages)
    assert any("multiline-secret.md" in message for message in escape_messages)
    assert any(item.rule == "reference.missing" and "references/missing.md" in item.message for item in diagnostics)


def test_file_uri_is_rejected_but_external_and_anchor_references_are_allowed() -> None:
    document = _skill_document() + (
        b"[local](file:///private/tmp/secret.md)\n"
        b"[drive](C:/Users/example/secret.md)\n"
        b"[web](https://example.com/docs)\n"
        b"[web2](http://example.com/docs)\n"
        b"[mail](mailto:owner@example.com)\n"
        b"[section](#details)\n"
    )
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    diagnostics = [item for item in validate_compiled_skill(package) if item.rule.startswith("reference.")]

    assert len(diagnostics) == 2
    assert {item.rule for item in diagnostics} == {"reference.absolute"}
    messages = {item.message for item in diagnostics}
    assert any("file:///private/tmp/secret.md" in message for message in messages)
    assert any("C:/Users/example/secret.md" in message for message in messages)


def test_nested_relative_reference_resolves_from_containing_file() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("references/detail.md"), b"# Detail\n", 0o644),
        CompiledSkillFile(PurePosixPath("references/index.md"), b"[detail](detail.md)\n", 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.rule.startswith("reference.") for item in diagnostics)


def test_openai_yaml_policy_and_asset_paths_are_validated_separately() -> None:
    openai = yaml.safe_dump(
        {
            "interface": {"icon_small": "../outside.svg", "unknown": "value"},
            "policy": {"allow_implicit_invocation": "false", "other": True},
            "extra": {},
        }
    ).encode()
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("agents/openai.yaml"), openai, 0o644),
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "openai.fields",
        "openai.interface-fields",
        "openai.asset-reference",
        "openai.policy",
    } <= rules


def test_package_structure_requires_sorted_unique_safe_paths_and_portable_modes() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("z.txt"), b"z", 0o644),
        CompiledSkillFile(PurePosixPath("../escape.txt"), b"x", 0o1000),
        CompiledSkillFile(PurePosixPath("z.txt"), b"duplicate", 0o644),
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "package.order",
        "package.path",
        "package.duplicate-path",
        "package.mode",
        "package.skill-document",
    } <= rules


def test_binary_assets_are_retained_without_text_token_false_positives() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("assets/image.bin"), b"\xff$ARGUMENTS\x00", 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.path == PurePosixPath("assets/image.bin") for item in diagnostics)


@pytest.mark.parametrize(
    ("path", "mode"),
    [
        (PurePosixPath("references/invalid.txt"), 0o644),
        (PurePosixPath("scripts/invalid.bin"), 0o755),
    ],
)
def test_non_utf8_executable_or_textual_file_fails_closed(path: PurePosixPath, mode: int) -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(path, b"\xff$CLAUDE_SKILL_DIR\n", mode),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == "token.utf8")
    assert diagnostic.path == path
    assert "isolation cannot be verified" in diagnostic.message
