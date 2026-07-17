"""Runtime-specific validation for compiled Agent Skill packages."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from .skill_compiler import (
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillDiagnostic,
    SkillRuntime,
    SkillSource,
)

_AGENT_SKILL_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
_AGENT_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OPENAI_TOP_LEVEL_FIELDS = {"interface", "policy", "dependencies"}
_OPENAI_INTERFACE_FIELDS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
_BINARY_ASSET_SUFFIXES = frozenset(
    {
        ".7z",
        ".avi",
        ".bin",
        ".bmp",
        ".bz2",
        ".class",
        ".db",
        ".dylib",
        ".eot",
        ".flac",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".mov",
        ".mp3",
        ".mp4",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".pyo",
        ".so",
        ".sqlite",
        ".tar",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xz",
        ".zip",
    }
)
_CLAUDE_EFFORT_VALUES = frozenset({"low", "medium", "high", "max"})
_NON_SUPPRESSIBLE_TOKEN_RULES = frozenset({"token.unresolved-placeholder"})


@dataclass(frozen=True)
class _TokenRule:
    id: str
    pattern: re.Pattern[str]
    message: str
    recovery: str


_COMMON_TOKEN_RULES = (
    _TokenRule(
        id="token.unresolved-placeholder",
        pattern=re.compile(r"\{\{forge:"),
        message="an unresolved Forge capability placeholder remains in emitted output",
        recovery="Declare the capability and provide a textual adapter binding before emitting the package.",
    ),
)

_CODEX_TOKEN_RULES = (
    _TokenRule(
        id="token.claude-arguments",
        pattern=re.compile(r"(?<![A-Za-z0-9_])\$ARGUMENTS\b"),
        message="Claude's $ARGUMENTS substitution leaked into a Codex package",
        recovery="Represent task input with {{forge:task_arguments}} and bind it only after the Codex probe.",
    ),
    _TokenRule(
        id="token.claude-skill-dir",
        pattern=re.compile(r"\$(?:\{CLAUDE_SKILL_DIR(?=[^A-Za-z0-9_]|$)|CLAUDE_SKILL_DIR\b)"),
        message="Claude's skill-directory variable leaked into a Codex package",
        recovery="Use resource_loading or packaged_script explicitly; packaged scripts need their own proven binding.",
    ),
    _TokenRule(
        id="token.claude-home-path",
        pattern=re.compile(r"(?:\$HOME|~)/\.claude(?:/|\b)"),
        message="a Claude installation-home path leaked into a Codex package",
        recovery="Represent the runtime installation home as an explicit capability or exclude the file from Codex.",
    ),
    _TokenRule(
        id="token.claude-session-id",
        pattern=re.compile(r"\$\{?CLAUDE_SESSION_ID\}?"),
        message="Claude's session identifier leaked into a Codex package",
        recovery="Model session identity as an explicit capability or exclude this skill from Codex.",
    ),
    _TokenRule(
        id="token.claude-command-name",
        pattern=re.compile(r"/forge:[a-z0-9][a-z0-9-]*"),
        message="a Claude slash-command selector leaked into a Codex package",
        recovery="Render the runtime's invocation form from adapter data rather than embedding /forge:<name>.",
    ),
    _TokenRule(
        id="token.claude-dynamic-command",
        pattern=re.compile(r"!`\s*forge\b"),
        message="a Claude dynamic command pre-step leaked into a Codex package",
        recovery="Lift the pre-step into a typed capability with an evidence-backed Codex binding.",
    ),
    _TokenRule(
        id="token.claude-subagent-type",
        pattern=re.compile(r"\bsubagent_type\b"),
        message="Claude subagent_type syntax leaked into a Codex package",
        recovery="Use the subagents or exploration capability and bind it in the Codex adapter.",
    ),
    _TokenRule(
        id="token.claude-interaction-tool",
        pattern=re.compile(r"\bAskUserQuestion\b"),
        message="the Claude AskUserQuestion tool leaked into a Codex package",
        recovery="Use the user_interaction capability or keep this skill Claude-only.",
    ),
    _TokenRule(
        id="token.claude-agent-tool",
        pattern=re.compile(
            r"`(?:Agent|Explore)`|\bAgent tool\b|\bExplore agent\b|\bTool:\s*(?:Agent|Explore)\b",
            re.IGNORECASE,
        ),
        message="Claude Agent/Explore tool syntax leaked into a Codex package",
        recovery="Use the exploration/subagents capability and add a reviewed Codex binding.",
    ),
    _TokenRule(
        id="token.claude-read-tool",
        pattern=re.compile(r"\bRead tool\b|\b(?:call|send|use) `Read`|\bTool:\s*Read\b", re.IGNORECASE),
        message="Claude Read tool syntax leaked into a Codex package",
        recovery="Describe package-relative resource loading neutrally and let the runtime adapter bind the operation.",
    ),
    _TokenRule(
        id="token.claude-hook-contract",
        pattern=re.compile(r"\bPreToolUse\b"),
        message="a Claude PreToolUse hook contract leaked into a Codex package",
        recovery="Move Claude hook behavior into its adapter or replace it with runtime-neutral guidance.",
    ),
    _TokenRule(
        id="token.claude-file-reference",
        pattern=re.compile(r"\bClaude Code file reference syntax\b", re.IGNORECASE),
        message="Claude file-reference syntax leaked into a Codex package",
        recovery="Describe target normalization without relying on Claude's @ file-reference convention.",
    ),
    _TokenRule(
        id="token.claude-default-model",
        pattern=re.compile(r"\bClaude Code default\b", re.IGNORECASE),
        message="a Claude-specific default-model label leaked into a Codex package",
        recovery="Use a runtime-neutral fallback label or bind the runtime/default-model label explicitly.",
    ),
)


def validate_compiled_skill(
    package: CompiledSkillPackage,
) -> tuple[SkillDiagnostic, ...]:
    """Return every deterministic validation failure for ``package``.

    Validation covers the complete emitted tree, not only ``SKILL.md``. Binary
    resources are retained but skipped by textual token/reference scans.
    """

    diagnostics: list[SkillDiagnostic] = []
    file_map: dict[PurePosixPath, CompiledSkillFile] = {}
    actual_order = tuple(package_file.path.as_posix() for package_file in package.files)
    if actual_order != tuple(sorted(actual_order)):
        diagnostics.append(
            _diagnostic(
                package,
                "package.order",
                "emitted package files are not in stable path order",
                "Sort CompiledSkillFile entries by their POSIX relative path.",
            )
        )

    for package_file in package.files:
        problem = _path_problem(package_file.path)
        if problem is not None:
            diagnostics.append(
                _diagnostic(
                    package,
                    "package.path",
                    problem,
                    "Emit a normalized relative POSIX path contained by the skill package.",
                    package_file.path,
                )
            )
        if package_file.path in file_map:
            diagnostics.append(
                _diagnostic(
                    package,
                    "package.duplicate-path",
                    "the emitted package contains this path more than once",
                    "Emit exactly one file for each package-relative path.",
                    package_file.path,
                )
            )
        else:
            file_map[package_file.path] = package_file
        if package_file.mode < 0 or package_file.mode & ~0o777:
            diagnostics.append(
                _diagnostic(
                    package,
                    "package.mode",
                    f"file mode {package_file.mode:#o} is outside the portable permission bits",
                    "Use a mode between 0o000 and 0o777; executable scripts normally use 0o755.",
                    package_file.path,
                )
            )

    skill_file = file_map.get(PurePosixPath("SKILL.md"))
    if skill_file is None:
        diagnostics.append(
            _diagnostic(
                package,
                "package.skill-document",
                "the emitted package has no top-level SKILL.md",
                "Emit one compiler-owned SKILL.md at the package root.",
                PurePosixPath("SKILL.md"),
            )
        )
    else:
        frontmatter, parse_diagnostics = _parse_frontmatter(package, skill_file)
        diagnostics.extend(parse_diagnostics)
        if frontmatter is not None:
            if package.runtime == SkillRuntime.CODEX:
                diagnostics.extend(_validate_codex_frontmatter(package, frontmatter))
            else:
                diagnostics.extend(_validate_claude_frontmatter(package, frontmatter))

    diagnostics.extend(_validate_token_isolation(package, file_map))
    diagnostics.extend(_validate_references(package, file_map))
    diagnostics.extend(_validate_openai_yaml(package, file_map))
    diagnostics.extend(_validate_allowances(package, file_map))
    return tuple(diagnostics)


def validate_neutral_skill_source(
    source: SkillSource,
    runtime: SkillRuntime,
) -> tuple[SkillDiagnostic, ...]:
    """Reject runtime syntax in every textual neutral source file.

    Capability placeholders are the normal escape from the neutral layer into an
    adapter. Token allowances never weaken the neutral-source gate. An auxiliary
    declared ineligible for Codex is explicitly Claude-specific and is therefore
    outside the shared neutral layer.
    """

    diagnostics: list[SkillDiagnostic] = []
    source_files = [(PurePosixPath("SKILL.md"), source.body)]
    source_files.extend((source_file.path, source_file.content) for source_file in source.files_for_runtime(runtime))
    for path, content in source_files:
        if runtime == SkillRuntime.CLAUDE_CODE and path in source.manifest.runtime_excluded_files.get(
            SkillRuntime.CODEX, frozenset()
        ):
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for rule in _CODEX_TOKEN_RULES:
            if rule.pattern.search(text):
                diagnostics.append(
                    SkillDiagnostic(
                        skill=source.manifest.name,
                        runtime=runtime,
                        path=path,
                        rule=f"neutral.{rule.id}",
                        message=f"neutral source contains runtime-specific syntax matched by '{rule.id}'",
                        recovery=rule.recovery,
                        source_path=source.source_path,
                    )
                )
    return tuple(diagnostics)


def _parse_frontmatter(
    package: CompiledSkillPackage,
    skill_file: CompiledSkillFile,
) -> tuple[dict[str, Any] | None, list[SkillDiagnostic]]:
    try:
        text = skill_file.content.decode("utf-8")
    except UnicodeDecodeError:
        return None, [
            _diagnostic(
                package,
                "frontmatter.utf8",
                "SKILL.md is not valid UTF-8",
                "Encode SKILL.md as UTF-8.",
                skill_file.path,
            )
        ]
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, [
            _diagnostic(
                package,
                "frontmatter.delimiter",
                "SKILL.md does not start with a YAML frontmatter delimiter",
                "Start SKILL.md with '---', a mapping, and a closing '---'.",
                skill_file.path,
            )
        ]
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing is None:
        return None, [
            _diagnostic(
                package,
                "frontmatter.delimiter",
                "SKILL.md has no closing YAML frontmatter delimiter",
                "Close the frontmatter mapping with a line containing only '---'.",
                skill_file.path,
            )
        ]
    try:
        value = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        return None, [
            _diagnostic(
                package,
                "frontmatter.yaml",
                f"SKILL.md frontmatter is malformed YAML: {exc}",
                "Fix the YAML mapping in the runtime adapter output.",
                skill_file.path,
            )
        ]
    if not isinstance(value, dict):
        return None, [
            _diagnostic(
                package,
                "frontmatter.mapping",
                "SKILL.md frontmatter is not a mapping",
                "Emit a YAML mapping with at least name and description.",
                skill_file.path,
            )
        ]
    return value, []


def _validate_claude_frontmatter(
    package: CompiledSkillPackage,
    frontmatter: Mapping[str, Any],
) -> list[SkillDiagnostic]:
    diagnostics: list[SkillDiagnostic] = []
    expected_name = f"forge:{package.name}"
    if frontmatter.get("name") != expected_name:
        diagnostics.append(
            _diagnostic(
                package,
                "claude.name",
                f"Claude package name must be '{expected_name}'",
                "Preserve the established forge:<skill> Claude selector in the Claude adapter.",
                PurePosixPath("SKILL.md"),
            )
        )
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        diagnostics.append(
            _diagnostic(
                package,
                "claude.description",
                "Claude package description must be a non-empty string",
                "Preserve the source skill description in Claude frontmatter.",
                PurePosixPath("SKILL.md"),
            )
        )

    string_fields = {
        "argument-hint": "a non-empty string",
        "agent": "a non-empty string",
        "license": "a non-empty string",
        "model": "a non-empty string",
    }
    for field, expected in string_fields.items():
        value = frontmatter.get(field)
        if field in frontmatter and (not isinstance(value, str) or not value.strip()):
            diagnostics.append(
                _diagnostic(
                    package,
                    f"claude.{field}",
                    f"Claude frontmatter {field} must be {expected} when present",
                    f"Set {field} to {expected}, or omit it.",
                    PurePosixPath("SKILL.md"),
                )
            )

    compatibility = frontmatter.get("compatibility")
    if "compatibility" in frontmatter and (
        not isinstance(compatibility, str) or not compatibility.strip() or len(compatibility) > 500
    ):
        diagnostics.append(
            _diagnostic(
                package,
                "claude.compatibility",
                "Claude frontmatter compatibility must be a non-empty string of at most 500 characters",
                "Omit compatibility or describe concrete requirements in 1-500 characters.",
                PurePosixPath("SKILL.md"),
            )
        )

    metadata = frontmatter.get("metadata")
    if "metadata" in frontmatter and not isinstance(metadata, dict):
        diagnostics.append(
            _diagnostic(
                package,
                "claude.metadata",
                "Claude frontmatter metadata must be a mapping",
                "Use a YAML mapping for metadata, or omit it.",
                PurePosixPath("SKILL.md"),
            )
        )

    for field in ("disable-model-invocation", "user-invocable"):
        value = frontmatter.get(field)
        if field in frontmatter and not isinstance(value, bool):
            diagnostics.append(
                _diagnostic(
                    package,
                    f"claude.{field}",
                    f"Claude frontmatter {field} must be a boolean",
                    f"Set {field} to true or false without quotes, or omit it.",
                    PurePosixPath("SKILL.md"),
                )
            )

    allowed_tools = frontmatter.get("allowed-tools")
    if "allowed-tools" in frontmatter and (not isinstance(allowed_tools, str) or not allowed_tools.strip()):
        diagnostics.append(
            _diagnostic(
                package,
                "claude.allowed-tools",
                "Claude frontmatter allowed-tools must be a non-empty string",
                "Set allowed-tools to Claude's documented tool-selector string, or omit it.",
                PurePosixPath("SKILL.md"),
            )
        )

    effort = frontmatter.get("effort")
    if "effort" in frontmatter and (not isinstance(effort, str) or effort not in _CLAUDE_EFFORT_VALUES):
        diagnostics.append(
            _diagnostic(
                package,
                "claude.effort",
                f"Claude frontmatter effort must be one of {sorted(_CLAUDE_EFFORT_VALUES)}",
                "Use low, medium, high, or max, or omit the effort override.",
                PurePosixPath("SKILL.md"),
            )
        )

    context = frontmatter.get("context")
    if "context" in frontmatter and context != "fork":
        diagnostics.append(
            _diagnostic(
                package,
                "claude.context",
                "Claude frontmatter context must be 'fork' when present",
                "Use context: fork for isolated execution, or omit context.",
                PurePosixPath("SKILL.md"),
            )
        )

    hooks = frontmatter.get("hooks")
    if "hooks" in frontmatter and not isinstance(hooks, dict):
        diagnostics.append(
            _diagnostic(
                package,
                "claude.hooks",
                "Claude frontmatter hooks must be a mapping",
                "Use Claude's documented skill-scoped hooks mapping, or omit hooks.",
                PurePosixPath("SKILL.md"),
            )
        )
    return diagnostics


def _validate_codex_frontmatter(
    package: CompiledSkillPackage,
    frontmatter: Mapping[str, Any],
) -> list[SkillDiagnostic]:
    diagnostics: list[SkillDiagnostic] = []
    keys = set(frontmatter)
    unknown = sorted(
        (key for key in keys if not isinstance(key, str) or key not in _AGENT_SKILL_FIELDS),
        key=repr,
    )
    if unknown:
        diagnostics.append(
            _diagnostic(
                package,
                "codex.frontmatter-fields",
                f"Codex frontmatter contains fields outside the Agent Skills allowlist: {unknown}",
                "Move runtime policy to agents/openai.yaml and omit Claude-only top-level fields.",
                PurePosixPath("SKILL.md"),
            )
        )

    name = frontmatter.get("name")
    if name != package.name:
        diagnostics.append(
            _diagnostic(
                package,
                "codex.name-directory",
                f"frontmatter name {name!r} does not match package directory name '{package.name}'",
                "Use the neutral skill name for both the Codex package directory and frontmatter name.",
                PurePosixPath("SKILL.md"),
            )
        )
    if not isinstance(name, str) or not (1 <= len(name) <= 64) or _AGENT_SKILL_NAME_RE.fullmatch(name) is None:
        diagnostics.append(
            _diagnostic(
                package,
                "codex.name-format",
                "Codex skill name must be 1-64 lowercase letters/numbers/hyphens without edge or consecutive hyphens",
                "Choose a portable Agent Skills name such as 'code-review'.",
                PurePosixPath("SKILL.md"),
            )
        )

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        diagnostics.append(
            _diagnostic(
                package,
                "codex.description",
                "Codex skill description must be a non-empty string of at most 1024 characters",
                "Describe what the skill does and when to use it in 1-1024 characters.",
                PurePosixPath("SKILL.md"),
            )
        )

    license_value = frontmatter.get("license")
    if license_value is not None and (not isinstance(license_value, str) or not license_value.strip()):
        diagnostics.append(
            _diagnostic(
                package,
                "codex.license",
                "Agent Skills license must be a non-empty string when present",
                "Use a short license name or a relative reference to a bundled license file.",
                PurePosixPath("SKILL.md"),
            )
        )

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None and (
        not isinstance(compatibility, str) or not compatibility.strip() or len(compatibility) > 500
    ):
        diagnostics.append(
            _diagnostic(
                package,
                "codex.compatibility",
                "Agent Skills compatibility must be a non-empty string of at most 500 characters",
                "Omit compatibility or describe concrete requirements in 1-500 characters.",
                PurePosixPath("SKILL.md"),
            )
        )

    metadata = frontmatter.get("metadata")
    if metadata is not None and (
        not isinstance(metadata, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items())
    ):
        diagnostics.append(
            _diagnostic(
                package,
                "codex.metadata",
                "Agent Skills metadata must map string keys to string values",
                "Quote metadata values and keep the metadata field a flat string-to-string mapping.",
                PurePosixPath("SKILL.md"),
            )
        )

    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None and (
        not isinstance(allowed_tools, str)
        or not allowed_tools.strip()
        or "," in allowed_tools
        or " ".join(allowed_tools.split()) != allowed_tools
    ):
        diagnostics.append(
            _diagnostic(
                package,
                "codex.allowed-tools",
                "Agent Skills allowed-tools must be one normalized space-separated string without commas",
                "Emit a value such as 'Bash(git:*) Bash(jq:*) Read' or omit this experimental field.",
                PurePosixPath("SKILL.md"),
            )
        )
    return diagnostics


def _validate_token_isolation(
    package: CompiledSkillPackage,
    file_map: Mapping[PurePosixPath, CompiledSkillFile],
) -> list[SkillDiagnostic]:
    rules = _COMMON_TOKEN_RULES + (_CODEX_TOKEN_RULES if package.runtime == SkillRuntime.CODEX else ())
    allowances = (
        {
            (allowance.path, allowance.rule)
            for allowance in package.token_allowances
            if allowance.runtime == package.runtime
        }
        if package.runtime != SkillRuntime.CODEX
        else set()
    )
    diagnostics: list[SkillDiagnostic] = []
    for path, package_file in sorted(file_map.items(), key=lambda item: item[0].as_posix()):
        try:
            text = package_file.content.decode("utf-8")
        except UnicodeDecodeError:
            if _requires_utf8_token_scan(package_file):
                diagnostics.append(
                    _diagnostic(
                        package,
                        "token.utf8",
                        "an executable or text-like package file is not valid UTF-8, so token isolation cannot be verified",
                        "Encode executable and textual package files as UTF-8; reserve binary suffixes for inert assets.",
                        path,
                    )
                )
            continue
        for rule in rules:
            if (
                path,
                rule.id,
            ) in allowances and rule.id not in _NON_SUPPRESSIBLE_TOKEN_RULES:
                continue
            if rule.pattern.search(text):
                diagnostics.append(_diagnostic(package, rule.id, rule.message, rule.recovery, path))
    return diagnostics


def _validate_references(
    package: CompiledSkillPackage,
    file_map: Mapping[PurePosixPath, CompiledSkillFile],
) -> list[SkillDiagnostic]:
    diagnostics: list[SkillDiagnostic] = []
    for source_path, package_file in sorted(file_map.items(), key=lambda item: item[0].as_posix()):
        if source_path.suffix.lower() not in {".md", ".markdown"}:
            continue
        try:
            text = package_file.content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for raw_target in _iter_markdown_reference_targets(text):
            if not raw_target:
                continue
            if re.match(r"^[A-Za-z]:", raw_target):
                diagnostics.append(
                    _diagnostic(
                        package,
                        "reference.absolute",
                        f"reference '{raw_target}' uses an absolute drive path",
                        "Reference bundled files with a package-relative path.",
                        source_path,
                    )
                )
                continue
            split = urlsplit(raw_target)
            if split.scheme.lower() == "file":
                diagnostics.append(
                    _diagnostic(
                        package,
                        "reference.absolute",
                        f"reference '{raw_target}' uses a local file URI",
                        "Reference bundled files with a package-relative path.",
                        source_path,
                    )
                )
                continue
            if split.scheme or split.netloc or not split.path:
                continue
            referenced = unquote(split.path)
            if referenced.startswith("/"):
                diagnostics.append(
                    _diagnostic(
                        package,
                        "reference.absolute",
                        f"reference '{raw_target}' is absolute",
                        "Reference bundled files with a package-relative path.",
                        source_path,
                    )
                )
                continue
            normalized = posixpath.normpath((source_path.parent / referenced).as_posix())
            if normalized == ".." or normalized.startswith("../"):
                diagnostics.append(
                    _diagnostic(
                        package,
                        "reference.escape",
                        f"reference '{raw_target}' escapes the emitted skill package",
                        "Copy the dependency into the skill package and reference it relatively.",
                        source_path,
                    )
                )
                continue
            if _is_dynamic_reference(raw_target):
                continue
            target_path = PurePosixPath(normalized)
            if target_path not in file_map:
                diagnostics.append(
                    _diagnostic(
                        package,
                        "reference.missing",
                        f"reference '{raw_target}' resolves to missing package file '{target_path}'",
                        "Fix the relative path or include the referenced file in the compiled package.",
                        source_path,
                    )
                )
    return diagnostics


def _iter_markdown_reference_targets(text: str) -> tuple[str, ...]:
    """Return inline-link and reference-definition destinations.

    This deliberately small parser tracks balanced label brackets and destination
    parentheses. Regex-only matching misses nested labels such as
    ``[outer [inner]](path)`` and reference definitions such as ``[label]: path``.
    """

    targets = list(_iter_inline_markdown_targets(text))
    targets.extend(_iter_markdown_definition_targets(text))
    return tuple(targets)


def _iter_inline_markdown_targets(text: str) -> tuple[str, ...]:
    targets: list[str] = []
    cursor = 0
    while cursor < len(text):
        label_start = text.find("[", cursor)
        if label_start < 0:
            break
        if _is_escaped(text, label_start):
            cursor = label_start + 1
            continue
        label_end = _find_balanced_end(text, label_start, "[", "]")
        if label_end is None or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            cursor = label_start + 1
            continue
        target = _markdown_destination(text, label_end + 2, require_closing_parenthesis=True)
        if target is not None:
            targets.append(target)
        cursor = label_end + 2
    return tuple(targets)


def _iter_markdown_definition_targets(text: str) -> tuple[str, ...]:
    targets: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if len(line) - len(stripped) > 3 or not stripped.startswith("["):
            continue
        label_end = _find_balanced_end(stripped, 0, "[", "]")
        if label_end is None or stripped[label_end + 1 : label_end + 2] != ":":
            continue
        target = _markdown_destination(stripped, label_end + 2, require_closing_parenthesis=False)
        if target is None and not stripped[label_end + 2 :].strip() and index + 1 < len(lines):
            continuation = lines[index + 1]
            continuation_stripped = continuation.lstrip(" ")
            if len(continuation) - len(continuation_stripped) <= 3:
                target = _markdown_destination(continuation_stripped, 0, require_closing_parenthesis=False)
        if target is not None:
            targets.append(target)
    return tuple(targets)


def _markdown_destination(text: str, start: int, *, require_closing_parenthesis: bool) -> str | None:
    cursor = start
    while cursor < len(text) and text[cursor] in " \t\r\n":
        cursor += 1
    if cursor >= len(text):
        return None
    if text[cursor] == "<":
        end = cursor + 1
        while end < len(text):
            if text[end] == ">" and not _is_escaped(text, end):
                return text[cursor + 1 : end]
            if text[end] in "\r\n":
                return None
            end += 1
        return None

    destination_start = cursor
    parenthesis_depth = 0
    while cursor < len(text):
        character = text[cursor]
        if character == "\\":
            cursor += 2
            continue
        if character == "(":
            parenthesis_depth += 1
        elif character == ")":
            if parenthesis_depth == 0:
                return text[destination_start:cursor] or None
            parenthesis_depth -= 1
        elif character in " \t\r\n" and parenthesis_depth == 0:
            if require_closing_parenthesis and ")" not in text[cursor:]:
                return None
            return text[destination_start:cursor] or None
        cursor += 1
    if require_closing_parenthesis:
        return None
    return text[destination_start:cursor] or None


def _find_balanced_end(text: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    for index in range(start, len(text)):
        if _is_escaped(text, index):
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _validate_openai_yaml(
    package: CompiledSkillPackage,
    file_map: Mapping[PurePosixPath, CompiledSkillFile],
) -> list[SkillDiagnostic]:
    path = PurePosixPath("agents/openai.yaml")
    package_file = file_map.get(path)
    if package_file is None:
        return []
    if package.runtime != SkillRuntime.CODEX:
        return [
            _diagnostic(
                package,
                "openai.runtime",
                "agents/openai.yaml was emitted for a non-Codex package",
                "Keep Codex invocation/UI metadata in the Codex adapter only.",
                path,
            )
        ]
    try:
        value = yaml.safe_load(package_file.content)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return [
            _diagnostic(
                package,
                "openai.yaml",
                f"agents/openai.yaml is not valid UTF-8 YAML: {exc}",
                "Emit a UTF-8 YAML mapping from typed Codex adapter data.",
                path,
            )
        ]
    if not isinstance(value, dict):
        return [
            _diagnostic(
                package,
                "openai.mapping",
                "agents/openai.yaml must contain a mapping",
                "Emit interface, policy, or dependencies mappings.",
                path,
            )
        ]

    diagnostics: list[SkillDiagnostic] = []
    unknown_top = sorted(
        (key for key in value if not isinstance(key, str) or key not in _OPENAI_TOP_LEVEL_FIELDS),
        key=repr,
    )
    if unknown_top:
        diagnostics.append(
            _diagnostic(
                package,
                "openai.fields",
                f"agents/openai.yaml contains unsupported top-level fields: {unknown_top}",
                "Use only interface, policy, and dependencies in Codex metadata.",
                path,
            )
        )

    interface = value.get("interface")
    if interface is not None:
        if not isinstance(interface, dict):
            diagnostics.append(
                _diagnostic(
                    package,
                    "openai.interface",
                    "interface must be a mapping",
                    "Emit only typed string UI fields under interface.",
                    path,
                )
            )
        else:
            unknown_interface = sorted(
                (key for key in interface if not isinstance(key, str) or key not in _OPENAI_INTERFACE_FIELDS),
                key=repr,
            )
            if unknown_interface:
                diagnostics.append(
                    _diagnostic(
                        package,
                        "openai.interface-fields",
                        f"interface contains unsupported fields: {unknown_interface}",
                        "Use the documented Codex interface field names.",
                        path,
                    )
                )
            for key, item in interface.items():
                if key in _OPENAI_INTERFACE_FIELDS and (not isinstance(item, str) or not item.strip()):
                    diagnostics.append(
                        _diagnostic(
                            package,
                            "openai.interface-value",
                            f"interface.{key} must be a non-empty string",
                            "Set a non-empty string or omit the optional UI field.",
                            path,
                        )
                    )
            for icon_key in ("icon_small", "icon_large"):
                icon = interface.get(icon_key)
                if isinstance(icon, str):
                    diagnostics.extend(_validate_root_reference(package, file_map, path, icon_key, icon))

    policy = value.get("policy")
    if policy is not None:
        if not isinstance(policy, dict) or set(policy) != {"allow_implicit_invocation"}:
            diagnostics.append(
                _diagnostic(
                    package,
                    "openai.policy",
                    "policy must contain exactly the allow_implicit_invocation field",
                    "Emit policy.allow_implicit_invocation as a boolean, or omit policy.",
                    path,
                )
            )
        elif not isinstance(policy["allow_implicit_invocation"], bool):
            diagnostics.append(
                _diagnostic(
                    package,
                    "openai.invocation-policy",
                    "policy.allow_implicit_invocation must be a boolean",
                    "Use true or false without quotes.",
                    path,
                )
            )

    dependencies = value.get("dependencies")
    if dependencies is not None:
        if (
            not isinstance(dependencies, dict)
            or set(dependencies) != {"tools"}
            or not isinstance(dependencies.get("tools"), list)
        ):
            diagnostics.append(
                _diagnostic(
                    package,
                    "openai.dependencies",
                    "dependencies must be a mapping containing a tools list",
                    "Emit documented dependency tool records or omit dependencies.",
                    path,
                )
            )
        elif any(not isinstance(item, dict) for item in dependencies["tools"]):
            diagnostics.append(
                _diagnostic(
                    package,
                    "openai.dependency-tool",
                    "every dependencies.tools entry must be a mapping",
                    "Emit one mapping per declared Codex tool dependency.",
                    path,
                )
            )
    return diagnostics


def _validate_root_reference(
    package: CompiledSkillPackage,
    file_map: Mapping[PurePosixPath, CompiledSkillFile],
    source_path: PurePosixPath,
    field: str,
    raw_target: str,
) -> list[SkillDiagnostic]:
    split = urlsplit(raw_target)
    if split.scheme or split.netloc or not split.path or split.path.startswith("/"):
        return [
            _diagnostic(
                package,
                "openai.asset-reference",
                f"interface.{field} must reference a relative bundled asset, got {raw_target!r}",
                "Bundle the icon under the skill root and use a relative path such as './assets/icon.svg'.",
                source_path,
            )
        ]
    normalized = posixpath.normpath(unquote(split.path))
    if normalized == ".." or normalized.startswith("../") or PurePosixPath(normalized) not in file_map:
        return [
            _diagnostic(
                package,
                "openai.asset-reference",
                f"interface.{field} resolves outside the package or to a missing file: {raw_target!r}",
                "Bundle the icon and reference its package-root-relative path.",
                source_path,
            )
        ]
    return []


def _validate_allowances(
    package: CompiledSkillPackage,
    file_map: Mapping[PurePosixPath, CompiledSkillFile],
) -> list[SkillDiagnostic]:
    known_rules = {rule.id for rule in _COMMON_TOKEN_RULES + _CODEX_TOKEN_RULES}
    diagnostics: list[SkillDiagnostic] = []
    for allowance in package.token_allowances:
        if allowance.runtime != package.runtime:
            continue
        if allowance.path not in file_map:
            diagnostics.append(
                _diagnostic(
                    package,
                    "allowance.missing-path",
                    f"token allowance targets absent file '{allowance.path}'",
                    "Remove the stale allowance or emit the named file.",
                    allowance.path,
                )
            )
        if allowance.rule not in known_rules:
            diagnostics.append(
                _diagnostic(
                    package,
                    "allowance.unknown-rule",
                    f"token allowance names unknown rule '{allowance.rule}'",
                    "Use a stable validator token rule id.",
                    allowance.path,
                )
            )
        elif allowance.rule in _NON_SUPPRESSIBLE_TOKEN_RULES:
            diagnostics.append(
                _diagnostic(
                    package,
                    "allowance.token-gate",
                    f"token rule '{allowance.rule}' cannot be suppressed by an allowance",
                    "Remove the allowance and ensure the compiler resolves every Forge capability placeholder.",
                    allowance.path,
                )
            )
        elif package.runtime == SkillRuntime.CODEX:
            diagnostics.append(
                _diagnostic(
                    package,
                    "allowance.codex-token-gate",
                    f"Codex token rule '{allowance.rule}' cannot be suppressed by an allowance",
                    "Remove the allowance and neutralize or explicitly exclude the runtime-specific documentary file.",
                    allowance.path,
                )
            )
    return diagnostics


def _requires_utf8_token_scan(package_file: CompiledSkillFile) -> bool:
    return bool(package_file.mode & 0o111) or package_file.path.suffix.lower() not in _BINARY_ASSET_SUFFIXES


def _path_problem(path: PurePosixPath) -> str | None:
    raw = path.as_posix()
    if not raw or raw == ".":
        return "emitted package path is empty"
    if path.is_absolute() or raw.startswith("/"):
        return "emitted package path is absolute"
    if "\\" in raw:
        return "emitted package path contains a non-POSIX separator"
    if any(part in {"", ".", ".."} for part in path.parts):
        return "emitted package path is not normalized or escapes the package root"
    return None


def _is_dynamic_reference(target: str) -> bool:
    return any(marker in target for marker in ("$", "{{", "}}", "<", ">"))


def _diagnostic(
    package: CompiledSkillPackage,
    rule: str,
    message: str,
    recovery: str,
    path: PurePosixPath | None = None,
) -> SkillDiagnostic:
    return SkillDiagnostic(
        skill=package.name,
        runtime=package.runtime,
        path=path,
        rule=rule,
        message=message,
        recovery=recovery,
        source_path=package.source_path,
    )


__all__ = ["validate_compiled_skill", "validate_neutral_skill_source"]
