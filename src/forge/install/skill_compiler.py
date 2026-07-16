"""Pure compiler contracts for runtime-specific Agent Skill packages.

The compiler deliberately knows nothing about installer scopes or target paths.  It
accepts an immutable, in-memory :class:`SkillSource` and returns an immutable
package whose files are relative to the skill directory.

Neutral templates use two explicit placeholder forms::

    {{forge:<capability-id>}}
    {{forge:<path-capability-id>:<portable-relative-path>}}

For example, ``{{forge:task_arguments}}`` requests the adapter's textual binding
for :attr:`SkillCapability.TASK_ARGUMENTS`, while
``{{forge:packaged_script:scripts/check.sh}}`` asks the adapter to render a safe
reference to one bundled file. Path arguments must be normalized, portable,
package-relative paths that name an emitted source file. Placeholders are
expanded only in the neutral Markdown body and in auxiliary files marked
``template=True``. A capability must be declared by
``SkillManifest.required_capabilities`` and bound by the selected adapter.
Unknown, undeclared, unbound, malformed, or leftover placeholders fail
compilation; the compiler never guesses or deletes behavior.

``load_claude_skill_source`` is a transition bridge for the existing checked-in
Claude packages. It retains the original ``SKILL.md`` bytes so the Claude adapter
is byte-for-byte faithful. The Codex adapter does not copy that document: it
composes spec frontmatter and then validates the whole emitted package, which
rejects any remaining Claude-only body or resource token.
"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, TypeVar

import yaml


class SkillRuntime(str, Enum):
    """Runtime package dialects emitted by the compiler."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class SkillCapability(str, Enum):
    """Runtime behavior that neutral skill content may request explicitly."""

    TASK_ARGUMENTS = "task_arguments"
    RESOURCE_LOADING = "resource_loading"
    PACKAGED_SCRIPT = "packaged_script"
    MODEL_FAMILY = "model_family"
    EXPLORATION = "exploration"
    SUBAGENTS = "subagents"
    INVOCATION_POLICY = "invocation_policy"
    USER_INTERACTION = "user_interaction"
    FORGE_CLI = "forge_cli"


class CapabilityArgumentKind(str, Enum):
    """Argument contract for one capability placeholder."""

    NONE = "none"
    RELATIVE_PATH = "relative_path"


CAPABILITY_ARGUMENT_KINDS: Mapping[SkillCapability, CapabilityArgumentKind] = {
    capability: (
        CapabilityArgumentKind.RELATIVE_PATH
        if capability in {SkillCapability.RESOURCE_LOADING, SkillCapability.PACKAGED_SCRIPT}
        else CapabilityArgumentKind.NONE
    )
    for capability in SkillCapability
}


class SkillSourceFormat(str, Enum):
    """How a :class:`SkillSource` was authored."""

    NEUTRAL = "neutral"
    CLAUDE_BRIDGE = "claude_bridge"


@dataclass(frozen=True)
class CapabilityBinding:
    """One adapter's implementation of a neutral capability.

    ``text`` binds a non-parameter placeholder. ``relative_path_template`` binds
    a path capability and must contain the literal marker ``{path}``, which the
    compiler replaces only after validating the argument. If both are ``None``,
    the capability is implemented structurally (currently invocation policy).
    """

    text: str | None = None
    relative_path_template: str | None = None


@dataclass(frozen=True)
class CodexSkillInterface:
    """Optional Codex/ChatGPT UI fields written to ``agents/openai.yaml``."""

    display_name: str | None = None
    short_description: str | None = None
    icon_small: str | None = None
    icon_large: str | None = None
    brand_color: str | None = None
    default_prompt: str | None = None


@dataclass(frozen=True)
class TokenAllowance:
    """Explicit exemption for one validator rule at one emitted package path."""

    runtime: SkillRuntime
    path: PurePosixPath
    rule: str


@dataclass(frozen=True)
class SkillManifest:
    """Typed, runtime-neutral identity plus narrowly scoped adapter data.

    ``name`` is the unprefixed portable skill name (for example ``review``).
    Claude compilation renders it as ``forge:review`` while the Agent Skills /
    Codex package keeps ``review`` and validates that directory/name contract.
    """

    name: str
    description: str
    runtime_eligibility: frozenset[SkillRuntime] = frozenset({SkillRuntime.CLAUDE_CODE})
    required_capabilities: frozenset[SkillCapability] = frozenset()
    license: str | None = None
    compatibility: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    allowed_tools: str | None = None
    allow_implicit_invocation: bool | None = None
    claude_frontmatter: Mapping[str, Any] = field(default_factory=dict)
    codex_interface: CodexSkillInterface | None = None
    token_allowances: tuple[TokenAllowance, ...] = ()
    runtime_excluded_files: Mapping[SkillRuntime, frozenset[PurePosixPath]] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSourceFile:
    """One auxiliary source file relative to the skill package root."""

    path: PurePosixPath
    content: bytes
    mode: int = 0o644
    template: bool = False


@dataclass(frozen=True)
class SkillSource:
    """Complete in-memory input to the compiler.

    Auxiliary ``files`` must not contain ``SKILL.md``; the compiler owns that
    document and composes it from ``manifest`` plus ``body``. ``claude_document``
    is reserved for the compatibility bridge and lets Claude output retain its
    exact historical frontmatter formatting and byte content.
    """

    manifest: SkillManifest
    body: bytes
    files: tuple[SkillSourceFile, ...] = ()
    skill_mode: int = 0o644
    source_format: SkillSourceFormat = SkillSourceFormat.NEUTRAL
    source_path: str | None = None
    claude_document: bytes | None = None

    def files_for_runtime(self, runtime: SkillRuntime) -> tuple[SkillSourceFile, ...]:
        """Return auxiliary files eligible for one emitted runtime package."""

        excluded = self.manifest.runtime_excluded_files.get(runtime, frozenset())
        return tuple(source_file for source_file in self.files if source_file.path not in excluded)


@dataclass(frozen=True)
class CompiledSkillFile:
    """One deterministic output file relative to the skill package root."""

    path: PurePosixPath
    content: bytes
    mode: int


@dataclass(frozen=True)
class CompiledSkillPackage:
    """Validated runtime-specific skill package."""

    runtime: SkillRuntime
    name: str
    files: tuple[CompiledSkillFile, ...]
    source_path: str | None = None
    token_allowances: tuple[TokenAllowance, ...] = ()

    def file(self, path: str | PurePosixPath) -> CompiledSkillFile:
        """Return one package file or raise ``KeyError`` for an absent path."""

        wanted = PurePosixPath(path)
        for package_file in self.files:
            if package_file.path == wanted:
                return package_file
        raise KeyError(str(wanted))


@dataclass(frozen=True)
class SkillDiagnostic:
    """Actionable compiler/validator failure."""

    skill: str
    runtime: SkillRuntime
    rule: str
    message: str
    recovery: str
    path: PurePosixPath | None = None
    source_path: str | None = None
    capability: SkillCapability | None = None

    def __str__(self) -> str:
        location = f"{self.skill}/{self.path}" if self.path is not None else self.skill
        details = [f"rule: {self.rule}"]
        if self.capability is not None:
            details.append(f"capability: {self.capability.value}")
        if self.source_path is not None:
            details.append(f"source: {self.source_path}")
        return f"[{self.runtime.value}] {location}: {self.message} ({'; '.join(details)}). Recovery: {self.recovery}"


class SkillCompilationError(ValueError):
    """Raised when a source cannot produce a complete valid package."""

    def __init__(self, diagnostics: tuple[SkillDiagnostic, ...] | list[SkillDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("\n".join(str(diagnostic) for diagnostic in self.diagnostics))


@dataclass(frozen=True)
class SkillAdapter:
    """Typed runtime adapter selected by :func:`compile_skill`."""

    runtime: SkillRuntime
    capability_bindings: Mapping[SkillCapability, CapabilityBinding]


# Claude's bindings describe existing, verified syntax. Packaged scripts remain a
# separate capability even though both resource and executable paths currently
# share CLAUDE_SKILL_DIR. Codex task/resource/script bindings reflect the live
# discovery probe. Model context and exploration bindings preserve the existing
# Claude behavior while expressing the same intent without Claude-only syntax in
# Codex output.
CLAUDE_SKILL_ADAPTER = SkillAdapter(
    runtime=SkillRuntime.CLAUDE_CODE,
    capability_bindings={
        SkillCapability.TASK_ARGUMENTS: CapabilityBinding("$ARGUMENTS"),
        SkillCapability.RESOURCE_LOADING: CapabilityBinding(relative_path_template="${CLAUDE_SKILL_DIR}/{path}"),
        SkillCapability.PACKAGED_SCRIPT: CapabilityBinding(
            relative_path_template='FORGE_SKILL_RUNTIME=claude_code bash "${CLAUDE_SKILL_DIR}/{path}"'
        ),
        SkillCapability.MODEL_FAMILY: CapabilityBinding(
            "Model family: !`forge session show --field model_family 2>/dev/null || true` Main model:\n"
            "!`forge session show --field main_model 2>/dev/null || true`"
        ),
        SkillCapability.EXPLORATION: CapabilityBinding('the `Agent` tool with `subagent_type: "Explore"`'),
        SkillCapability.SUBAGENTS: CapabilityBinding("Agent"),
        SkillCapability.INVOCATION_POLICY: CapabilityBinding(),
        SkillCapability.USER_INTERACTION: CapabilityBinding("AskUserQuestion"),
        SkillCapability.FORGE_CLI: CapabilityBinding("forge"),
    },
)

CODEX_SKILL_ADAPTER = SkillAdapter(
    runtime=SkillRuntime.CODEX,
    capability_bindings={
        SkillCapability.TASK_ARGUMENTS: CapabilityBinding(
            "the task text supplied when this skill was invoked or selected"
        ),
        SkillCapability.RESOURCE_LOADING: CapabilityBinding(
            relative_path_template="Read `{path}` relative to the directory containing this SKILL.md"
        ),
        SkillCapability.PACKAGED_SCRIPT: CapabilityBinding(
            relative_path_template=(
                "Resolve `{path}` against the directory containing this SKILL.md, "
                "then execute the resulting absolute path with `FORGE_SKILL_RUNTIME=codex`"
            )
        ),
        SkillCapability.MODEL_FAMILY: CapabilityBinding(
            "Run `forge session show --field model_family` and "
            "`forge session show --field main_model`, then use their outputs as the model-family context"
        ),
        SkillCapability.EXPLORATION: CapabilityBinding(
            "runtime-native repository search and file reads, using parallel workers when independent searches "
            "can run concurrently"
        ),
        SkillCapability.INVOCATION_POLICY: CapabilityBinding(),
        SkillCapability.FORGE_CLI: CapabilityBinding("forge"),
    },
)


_PLACEHOLDER_RE = re.compile(r"\{\{forge:([a-z][a-z0-9_]*)(?::([^}\r\n]*))?\}\}")
_PLACEHOLDER_CANDIDATE_RE = re.compile(r"\{\{forge:([^}\r\n]*)\}\}")
_PORTABLE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

NEUTRAL_SKILL_MANIFEST = "forge-skill.yaml"
NEUTRAL_SKILL_CONTENT = "content.md"
NEUTRAL_SKILL_SCHEMA_VERSION = 1
_COMPILER_OWNED_SOURCE_PATHS = frozenset(
    {
        PurePosixPath(NEUTRAL_SKILL_MANIFEST),
        PurePosixPath(NEUTRAL_SKILL_CONTENT),
        PurePosixPath("SKILL.md"),
    }
)
_NEUTRAL_MANIFEST_FIELDS = {
    "schema_version",
    "name",
    "description",
    "runtimes",
    "capabilities",
    "license",
    "compatibility",
    "metadata",
    "allowed_tools",
    "allow_implicit_invocation",
    "claude_frontmatter",
    "codex_interface",
    "template_files",
    "token_allowances",
    "runtime_excluded_files",
}
_CODEX_INTERFACE_FIELDS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
_SKILL_SOURCE_EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SKILL_SOURCE_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_EnumT = TypeVar("_EnumT", bound=Enum)


def adapter_for_runtime(runtime: SkillRuntime) -> SkillAdapter:
    """Return Forge's default adapter for ``runtime``."""

    if runtime == SkillRuntime.CLAUDE_CODE:
        return CLAUDE_SKILL_ADAPTER
    if runtime == SkillRuntime.CODEX:
        return CODEX_SKILL_ADAPTER
    raise ValueError(f"Unsupported skill runtime: {runtime}")


def load_claude_skill_source(package_root: Path) -> SkillSource:
    """Read an existing Claude package into the typed compatibility bridge.

    This is the only filesystem-reading part of the compiler module. Compilation
    itself remains pure. Broken or external symlinks are rejected so the package
    remains self-contained. Existing relative aliases are dereferenced only when
    their target is another file inside the same package, matching today's
    copy-install bytes and executable modes.
    """

    skill_document_path = package_root / "SKILL.md"
    if not package_root.is_dir() or not skill_document_path.is_file():
        raise ValueError(f"Claude skill package must contain {skill_document_path}")

    document = skill_document_path.read_bytes()
    frontmatter, body = _parse_skill_document(document, str(skill_document_path))
    raw_name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError(f"{skill_document_path}: frontmatter 'name' must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{skill_document_path}: frontmatter 'description' must be a non-empty string")

    name = package_root.name
    auxiliary_files: list[SkillSourceFile] = []
    for source_file in sorted(package_root.rglob("*")):
        if source_file == skill_document_path or source_file.is_dir():
            continue
        if source_file.is_symlink():
            try:
                resolved = source_file.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError(f"{source_file}: skill source symlink cannot be resolved: {exc}") from exc
            if not resolved.is_relative_to(package_root.resolve()) or not resolved.is_file():
                raise ValueError(f"{source_file}: skill source symlink must target a file inside its package")
        if not source_file.is_file():
            continue
        auxiliary_files.append(
            SkillSourceFile(
                path=PurePosixPath(source_file.relative_to(package_root).as_posix()),
                content=source_file.read_bytes(),
                mode=stat.S_IMODE(source_file.stat().st_mode),
            )
        )

    return SkillSource(
        manifest=SkillManifest(
            name=name,
            description=description,
            claude_frontmatter=dict(frontmatter),
        ),
        body=body,
        files=tuple(auxiliary_files),
        skill_mode=stat.S_IMODE(skill_document_path.stat().st_mode),
        source_format=SkillSourceFormat.CLAUDE_BRIDGE,
        source_path=str(package_root),
        claude_document=document,
    )


def load_claude_skill_sources(skills_root: Path) -> tuple[SkillSource, ...]:
    """Load existing skill package directories in deterministic name order."""

    if not skills_root.is_dir():
        raise ValueError(f"Skill source root is not a directory: {skills_root}")
    package_roots = sorted(path for path in skills_root.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())
    return tuple(load_claude_skill_source(package_root) for package_root in package_roots)


def load_neutral_skill_source(package_root: Path) -> SkillSource:
    """Load one ``forge-skill.yaml`` + ``content.md`` neutral source package.

    Every other installable file in the package is an auxiliary source file,
    except top-level ``SKILL.md`` which is treated as a legacy/generated artifact
    during migration. ``template_files`` opts auxiliary UTF-8 files into the same
    capability placeholder grammar used by ``content.md``.
    """

    manifest_path = package_root / NEUTRAL_SKILL_MANIFEST
    content_path = package_root / NEUTRAL_SKILL_CONTENT
    if not package_root.is_dir() or not manifest_path.is_file():
        raise ValueError(f"Neutral skill package must contain {manifest_path}")
    if not content_path.is_file():
        raise ValueError(f"Neutral skill package must contain {content_path}")

    try:
        raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{manifest_path}: cannot read neutral skill manifest: {exc}") from exc
    if not isinstance(raw_manifest, dict) or any(not isinstance(key, str) for key in raw_manifest):
        raise ValueError(f"{manifest_path}: neutral skill manifest must be a string-keyed mapping")
    unknown_fields = sorted(set(raw_manifest) - _NEUTRAL_MANIFEST_FIELDS)
    if unknown_fields:
        raise ValueError(f"{manifest_path}: unknown neutral skill manifest fields: {unknown_fields}")
    schema_version = raw_manifest.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError(
            f"{manifest_path}: schema_version must be {NEUTRAL_SKILL_SCHEMA_VERSION}, got {schema_version!r}"
        )

    name = _required_manifest_string(raw_manifest, "name", manifest_path)
    if name != package_root.name:
        raise ValueError(f"{manifest_path}: name {name!r} must match package directory {package_root.name!r}")
    description = _required_manifest_string(raw_manifest, "description", manifest_path)
    runtimes = _manifest_enum_set(raw_manifest, "runtimes", SkillRuntime, manifest_path, required=True)
    capabilities = _manifest_enum_set(raw_manifest, "capabilities", SkillCapability, manifest_path)

    metadata = raw_manifest.get("metadata", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()
    ):
        raise ValueError(f"{manifest_path}: metadata must map string keys to string values")
    claude_frontmatter = raw_manifest.get("claude_frontmatter", {})
    if not isinstance(claude_frontmatter, dict) or any(not isinstance(key, str) for key in claude_frontmatter):
        raise ValueError(f"{manifest_path}: claude_frontmatter must be a string-keyed mapping")
    if {"name", "description"} & set(claude_frontmatter):
        raise ValueError(f"{manifest_path}: claude_frontmatter may not override name or description")

    codex_interface_value = raw_manifest.get("codex_interface")
    codex_interface: CodexSkillInterface | None = None
    if codex_interface_value is not None:
        if not isinstance(codex_interface_value, dict) or any(
            not isinstance(key, str) for key in codex_interface_value
        ):
            raise ValueError(f"{manifest_path}: codex_interface must be a string-keyed mapping")
        unknown_interface = sorted(set(codex_interface_value) - _CODEX_INTERFACE_FIELDS)
        if unknown_interface:
            raise ValueError(f"{manifest_path}: unknown codex_interface fields: {unknown_interface}")
        if any(not isinstance(value, str) for value in codex_interface_value.values()):
            raise ValueError(f"{manifest_path}: codex_interface values must be strings")
        codex_interface = CodexSkillInterface(**codex_interface_value)

    template_file_values = _manifest_string_list(raw_manifest, "template_files", manifest_path)
    template_files: set[PurePosixPath] = set()
    for raw_path in template_file_values:
        problem = _path_argument_problem(raw_path)
        if problem is not None:
            raise ValueError(f"{manifest_path}: template_files path {raw_path!r} {problem}")
        template_path = PurePosixPath(raw_path)
        if template_path in {
            PurePosixPath(NEUTRAL_SKILL_MANIFEST),
            PurePosixPath(NEUTRAL_SKILL_CONTENT),
            PurePosixPath("SKILL.md"),
        }:
            raise ValueError(f"{manifest_path}: template_files may name only auxiliary files, got {raw_path!r}")
        template_files.add(template_path)
    if len(template_files) != len(template_file_values):
        raise ValueError(f"{manifest_path}: template_files contains duplicate paths")

    runtime_exclusions_value = raw_manifest.get("runtime_excluded_files", {})
    if not isinstance(runtime_exclusions_value, dict) or any(
        not isinstance(key, str) for key in runtime_exclusions_value
    ):
        raise ValueError(f"{manifest_path}: runtime_excluded_files must be a runtime-keyed mapping")
    runtime_excluded_files: dict[SkillRuntime, frozenset[PurePosixPath]] = {}
    for raw_runtime, raw_paths in runtime_exclusions_value.items():
        try:
            excluded_runtime = SkillRuntime(raw_runtime)
        except ValueError as exc:
            raise ValueError(f"{manifest_path}: runtime_excluded_files has unknown runtime {raw_runtime!r}") from exc
        if excluded_runtime not in runtimes:
            raise ValueError(
                f"{manifest_path}: runtime_excluded_files names undeclared runtime {excluded_runtime.value!r}"
            )
        if not isinstance(raw_paths, list) or any(
            not isinstance(raw_path, str) or not raw_path for raw_path in raw_paths
        ):
            raise ValueError(
                f"{manifest_path}: runtime_excluded_files.{excluded_runtime.value} must be a list of explicit paths"
            )
        excluded_paths: set[PurePosixPath] = set()
        for raw_path in raw_paths:
            problem = _runtime_exclusion_path_problem(raw_path)
            if problem is not None:
                raise ValueError(
                    f"{manifest_path}: runtime_excluded_files.{excluded_runtime.value} path {raw_path!r} {problem}"
                )
            excluded_paths.add(PurePosixPath(raw_path))
        if len(excluded_paths) != len(raw_paths):
            raise ValueError(
                f"{manifest_path}: runtime_excluded_files.{excluded_runtime.value} contains duplicate paths"
            )
        runtime_excluded_files[excluded_runtime] = frozenset(excluded_paths)

    token_allowances_value = raw_manifest.get("token_allowances", [])
    if not isinstance(token_allowances_value, list):
        raise ValueError(f"{manifest_path}: token_allowances must be a list")
    token_allowances: list[TokenAllowance] = []
    for index, item in enumerate(token_allowances_value):
        label = f"{manifest_path}: token_allowances[{index}]"
        if not isinstance(item, dict) or set(item) != {"runtime", "path", "rule"}:
            raise ValueError(f"{label} must contain exactly runtime, path, and rule")
        runtime_value = item["runtime"]
        path_value = item["path"]
        rule_value = item["rule"]
        if not all(isinstance(value, str) for value in (runtime_value, path_value, rule_value)):
            raise ValueError(f"{label} values must be strings")
        try:
            allowance_runtime = SkillRuntime(runtime_value)
        except ValueError as exc:
            raise ValueError(f"{label} has unknown runtime {runtime_value!r}") from exc
        path_problem = _path_argument_problem(path_value)
        if path_problem is not None:
            raise ValueError(f"{label} path {path_value!r} {path_problem}")
        token_allowances.append(
            TokenAllowance(runtime=allowance_runtime, path=PurePosixPath(path_value), rule=rule_value)
        )

    optional_strings: dict[str, str | None] = {}
    for field_name in ("license", "compatibility", "allowed_tools"):
        value = raw_manifest.get(field_name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{manifest_path}: {field_name} must be a string when present")
        optional_strings[field_name] = value
    allow_implicit_invocation = raw_manifest.get("allow_implicit_invocation")
    if allow_implicit_invocation is not None and not isinstance(allow_implicit_invocation, bool):
        raise ValueError(f"{manifest_path}: allow_implicit_invocation must be a boolean when present")

    auxiliary_files: list[SkillSourceFile] = []
    for source_file in sorted(package_root.rglob("*")):
        if source_file.is_dir():
            continue
        relative_path = PurePosixPath(source_file.relative_to(package_root).as_posix())
        if relative_path in _COMPILER_OWNED_SOURCE_PATHS or not _is_skill_source_file(relative_path):
            continue
        content, mode = _read_contained_source_file(package_root, source_file)
        auxiliary_files.append(
            SkillSourceFile(
                path=relative_path,
                content=content,
                mode=mode,
                template=relative_path in template_files,
            )
        )
    available_paths = {source_file.path for source_file in auxiliary_files}
    missing_template_files = sorted(template_files - available_paths, key=PurePosixPath.as_posix)
    if missing_template_files:
        raise ValueError(f"{manifest_path}: template_files names missing auxiliary files: {missing_template_files}")
    missing_runtime_exclusions = {
        runtime.value: sorted(paths - available_paths, key=PurePosixPath.as_posix)
        for runtime, paths in runtime_excluded_files.items()
        if paths - available_paths
    }
    if missing_runtime_exclusions:
        raise ValueError(
            f"{manifest_path}: runtime_excluded_files names missing auxiliary files: {missing_runtime_exclusions}"
        )

    return SkillSource(
        manifest=SkillManifest(
            name=name,
            description=description,
            runtime_eligibility=frozenset(runtimes),
            required_capabilities=frozenset(capabilities),
            license=optional_strings["license"],
            compatibility=optional_strings["compatibility"],
            metadata=dict(metadata),
            allowed_tools=optional_strings["allowed_tools"],
            allow_implicit_invocation=allow_implicit_invocation,
            claude_frontmatter=dict(claude_frontmatter),
            codex_interface=codex_interface,
            token_allowances=tuple(token_allowances),
            runtime_excluded_files=runtime_excluded_files,
        ),
        body=content_path.read_bytes(),
        files=tuple(auxiliary_files),
        skill_mode=stat.S_IMODE(content_path.stat().st_mode),
        source_format=SkillSourceFormat.NEUTRAL,
        source_path=str(package_root),
    )


def load_skill_source(package_root: Path) -> SkillSource:
    """Load a neutral package when declared, otherwise use the Claude bridge."""

    if (package_root / NEUTRAL_SKILL_MANIFEST).exists():
        return load_neutral_skill_source(package_root)
    return load_claude_skill_source(package_root)


def load_skill_sources(skills_root: Path) -> tuple[SkillSource, ...]:
    """Load a deterministic mixed set of neutral and legacy skill packages."""

    if not skills_root.is_dir():
        raise ValueError(f"Skill source root is not a directory: {skills_root}")
    package_roots = sorted(
        path
        for path in skills_root.iterdir()
        if path.is_dir() and ((path / NEUTRAL_SKILL_MANIFEST).exists() or (path / "SKILL.md").is_file())
    )
    return tuple(load_skill_source(package_root) for package_root in package_roots)


def compile_skill(source: SkillSource, adapter: SkillAdapter) -> CompiledSkillPackage:
    """Compile and validate one runtime package without installer I/O."""

    diagnostics = _validate_source(source, adapter)
    if diagnostics:
        raise SkillCompilationError(_with_source_path(diagnostics, source.source_path))

    rendered_body = source.body
    if source.source_format == SkillSourceFormat.NEUTRAL:
        rendered_body = _render_template(source.body, source, adapter, PurePosixPath("SKILL.md"))
    if (
        adapter.runtime == SkillRuntime.CLAUDE_CODE
        and source.source_format == SkillSourceFormat.CLAUDE_BRIDGE
        and source.claude_document is not None
    ):
        skill_document = source.claude_document
    else:
        frontmatter = _frontmatter_for(source.manifest, adapter.runtime)
        skill_document = _render_skill_document(frontmatter, rendered_body, source, adapter)

    compiled_files = [
        CompiledSkillFile(
            path=PurePosixPath("SKILL.md"),
            content=skill_document,
            mode=source.skill_mode,
        )
    ]
    openai_yaml = _render_openai_yaml(source.manifest) if adapter.runtime == SkillRuntime.CODEX else None
    if openai_yaml is not None:
        compiled_files.append(
            CompiledSkillFile(
                path=PurePosixPath("agents/openai.yaml"),
                content=openai_yaml,
                mode=0o644,
            )
        )
    for source_file in source.files_for_runtime(adapter.runtime):
        content = source_file.content
        if source_file.template:
            content = _render_template(content, source, adapter, source_file.path)
        compiled_files.append(CompiledSkillFile(path=source_file.path, content=content, mode=source_file.mode))

    package = CompiledSkillPackage(
        runtime=adapter.runtime,
        name=source.manifest.name,
        files=tuple(sorted(compiled_files, key=lambda item: item.path.as_posix())),
        source_path=source.source_path,
        token_allowances=source.manifest.token_allowances,
    )

    # Lazy import avoids a compiler/validator import cycle while keeping package
    # validation mandatory at the build boundary.
    from .skill_validation import validate_compiled_skill

    validation_diagnostics = validate_compiled_skill(package)
    if validation_diagnostics:
        raise SkillCompilationError(_with_source_path(validation_diagnostics, source.source_path))
    return package


def compile_skill_for_runtime(source: SkillSource, runtime: SkillRuntime) -> CompiledSkillPackage:
    """Compile with Forge's default adapter for ``runtime``."""

    return compile_skill(source, adapter_for_runtime(runtime))


def _validate_source(source: SkillSource, adapter: SkillAdapter) -> list[SkillDiagnostic]:
    diagnostics: list[SkillDiagnostic] = []
    runtime = adapter.runtime
    manifest = source.manifest

    if runtime not in manifest.runtime_eligibility:
        diagnostics.append(
            SkillDiagnostic(
                skill=manifest.name,
                runtime=runtime,
                path=None,
                rule="source.runtime-eligibility",
                message=f"the source manifest does not declare {runtime.value} package eligibility",
                recovery="Opt in only after the source is neutralized and the runtime package passes its validator.",
            )
        )

    if not manifest.name:
        diagnostics.append(
            SkillDiagnostic(
                skill="<unnamed>",
                runtime=runtime,
                path=None,
                rule="source.name",
                message="the neutral manifest name is empty",
                recovery="Set SkillManifest.name to the portable package directory name.",
            )
        )
    if not manifest.description:
        diagnostics.append(
            SkillDiagnostic(
                skill=manifest.name or "<unnamed>",
                runtime=runtime,
                path=PurePosixPath("SKILL.md"),
                rule="source.description",
                message="the neutral manifest description is empty",
                recovery="Add a description that states what the skill does and when to use it.",
            )
        )

    if (
        manifest.allow_implicit_invocation is not None
        and SkillCapability.INVOCATION_POLICY not in manifest.required_capabilities
    ):
        diagnostics.append(
            SkillDiagnostic(
                skill=manifest.name,
                runtime=runtime,
                path=PurePosixPath("SKILL.md"),
                rule="source.invocation-policy-capability",
                message="allow_implicit_invocation is set without declaring the invocation_policy capability",
                recovery="Add SkillCapability.INVOCATION_POLICY to required_capabilities.",
                capability=SkillCapability.INVOCATION_POLICY,
            )
        )
    if (
        SkillCapability.INVOCATION_POLICY in manifest.required_capabilities
        and manifest.allow_implicit_invocation is None
    ):
        diagnostics.append(
            SkillDiagnostic(
                skill=manifest.name,
                runtime=runtime,
                path=PurePosixPath("SKILL.md"),
                rule="source.invocation-policy-value",
                message="the invocation_policy capability has no allow_implicit_invocation value",
                recovery="Set allow_implicit_invocation explicitly so both runtime adapters can preserve the policy.",
                capability=SkillCapability.INVOCATION_POLICY,
            )
        )

    for capability in sorted(manifest.required_capabilities, key=lambda item: item.value):
        binding = adapter.capability_bindings.get(capability)
        argument_kind = CAPABILITY_ARGUMENT_KINDS[capability]
        missing_binding = binding is None
        if binding is not None and argument_kind == CapabilityArgumentKind.RELATIVE_PATH:
            missing_binding = (
                binding.relative_path_template is None or binding.relative_path_template.count("{path}") != 1
            )
        elif binding is not None and capability != SkillCapability.INVOCATION_POLICY and binding.text is None:
            missing_binding = True
        if missing_binding:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=None,
                    rule="capability.unbound",
                    message=f"required capability '{capability.value}' has no {runtime.value} binding",
                    recovery=(
                        "Add an evidence-backed binding to the runtime adapter, or exclude this skill from that runtime."
                    ),
                    capability=capability,
                )
            )

    seen: set[PurePosixPath] = {PurePosixPath("SKILL.md")}
    for source_file in source.files:
        path_problem = _source_path_problem(source_file.path)
        if path_problem is not None:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=source_file.path,
                    rule="package.path",
                    message=path_problem,
                    recovery="Use a unique relative POSIX path contained by the skill package.",
                )
            )
        elif source_file.path in seen:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=source_file.path,
                    rule="package.duplicate-path",
                    message="the source declares this package path more than once",
                    recovery="Keep exactly one source file for each emitted package path.",
                )
            )
        seen.add(source_file.path)

        if source_file.mode < 0 or source_file.mode & ~0o777:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=source_file.path,
                    rule="package.mode",
                    message=f"file mode {source_file.mode:#o} is outside the portable permission bits",
                    recovery="Use a mode between 0o000 and 0o777; scripts normally use 0o755.",
                )
            )

        if source.source_format == SkillSourceFormat.NEUTRAL and source_file.path == PurePosixPath(
            "agents/openai.yaml"
        ):
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=source_file.path,
                    rule="source.openai-metadata-ownership",
                    message="neutral auxiliary files may not own runtime-specific agents/openai.yaml",
                    recovery="Remove the auxiliary file and express policy/UI metadata through SkillManifest.",
                )
            )

    available_paths = seen - {PurePosixPath("SKILL.md")}
    for excluded_runtime in sorted(manifest.runtime_excluded_files, key=lambda item: item.value):
        excluded_paths = manifest.runtime_excluded_files[excluded_runtime]
        if source.source_format != SkillSourceFormat.NEUTRAL:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=None,
                    rule="source.runtime-exclusion-format",
                    message="runtime-specific file exclusions are valid only for neutral source packages",
                    recovery="Remove the exclusions from a legacy bridge or migrate the package to neutral source.",
                )
            )
        if excluded_runtime not in manifest.runtime_eligibility:
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=None,
                    rule="source.runtime-exclusion-runtime",
                    message=f"file exclusions name undeclared runtime '{excluded_runtime.value}'",
                    recovery="Remove the stale runtime key or add that runtime to runtime_eligibility.",
                )
            )
        for excluded_path in sorted(excluded_paths, key=PurePosixPath.as_posix):
            path_problem = _runtime_exclusion_path_problem(excluded_path.as_posix())
            if path_problem is not None:
                diagnostics.append(
                    SkillDiagnostic(
                        skill=manifest.name,
                        runtime=runtime,
                        path=excluded_path,
                        rule="source.runtime-exclusion-path",
                        message=f"runtime-specific exclusion path {path_problem}",
                        recovery="Name an explicit Markdown auxiliary under references/.",
                    )
                )
            elif excluded_path not in available_paths:
                diagnostics.append(
                    SkillDiagnostic(
                        skill=manifest.name,
                        runtime=runtime,
                        path=excluded_path,
                        rule="source.runtime-exclusion-missing",
                        message="runtime-specific exclusion names no auxiliary source file",
                        recovery="Add the documentary auxiliary or remove the stale exclusion.",
                    )
                )
    for source_path in sorted(available_paths, key=PurePosixPath.as_posix):
        if manifest.runtime_eligibility and all(
            source_path in manifest.runtime_excluded_files.get(eligible_runtime, frozenset())
            for eligible_runtime in manifest.runtime_eligibility
        ):
            diagnostics.append(
                SkillDiagnostic(
                    skill=manifest.name,
                    runtime=runtime,
                    path=source_path,
                    rule="source.runtime-exclusion-all",
                    message="auxiliary source file is excluded from every eligible runtime",
                    recovery="Remove the unused file or keep it in at least one runtime package.",
                )
            )

    if source.skill_mode < 0 or source.skill_mode & ~0o777:
        diagnostics.append(
            SkillDiagnostic(
                skill=manifest.name,
                runtime=runtime,
                path=PurePosixPath("SKILL.md"),
                rule="package.mode",
                message=f"file mode {source.skill_mode:#o} is outside the portable permission bits",
                recovery="Use a mode between 0o000 and 0o777; SKILL.md normally uses 0o644.",
            )
        )

    templated: list[tuple[PurePosixPath, bytes]] = []
    if source.source_format == SkillSourceFormat.NEUTRAL:
        templated.append((PurePosixPath("SKILL.md"), source.body))
    templated.extend(
        (source_file.path, source_file.content)
        for source_file in source.files_for_runtime(runtime)
        if source_file.template
    )
    for path, content in templated:
        diagnostics.extend(_validate_placeholders(content, source, adapter, path))
    if source.source_format == SkillSourceFormat.NEUTRAL:
        from .skill_validation import validate_neutral_skill_source

        diagnostics.extend(validate_neutral_skill_source(source, runtime))
    return diagnostics


def _validate_placeholders(
    content: bytes,
    source: SkillSource,
    adapter: SkillAdapter,
    path: PurePosixPath,
) -> list[SkillDiagnostic]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [
            SkillDiagnostic(
                skill=source.manifest.name,
                runtime=adapter.runtime,
                path=path,
                rule="template.utf8",
                message="a templated source file is not valid UTF-8",
                recovery="Mark binary data template=False or encode the template as UTF-8.",
            )
        ]

    diagnostics: list[SkillDiagnostic] = []
    available_paths = {source_file.path for source_file in source.files_for_runtime(adapter.runtime)}
    for match in _PLACEHOLDER_CANDIDATE_RE.finditer(text):
        payload = match.group(1)
        capability_id, separator, argument = payload.partition(":")
        argument_value = argument if separator else None
        try:
            capability = SkillCapability(capability_id)
        except ValueError:
            diagnostics.append(
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=path,
                    rule="template.unknown-capability",
                    message=f"placeholder names unknown capability '{capability_id}'",
                    recovery=(
                        "Use {{forge:<capability-id>}} or " "{{forge:<path-capability-id>:<portable-relative-path>}}."
                    ),
                )
            )
            continue
        if capability not in source.manifest.required_capabilities:
            diagnostics.append(
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=path,
                    rule="template.undeclared-capability",
                    message=f"placeholder uses undeclared capability '{capability.value}'",
                    recovery=f"Declare SkillCapability.{capability.name} in required_capabilities.",
                    capability=capability,
                )
            )
            continue
        argument_kind = CAPABILITY_ARGUMENT_KINDS[capability]
        binding = adapter.capability_bindings.get(capability)
        if argument_kind == CapabilityArgumentKind.RELATIVE_PATH:
            if argument_value is None or not argument_value:
                diagnostics.append(
                    SkillDiagnostic(
                        skill=source.manifest.name,
                        runtime=adapter.runtime,
                        path=path,
                        rule="template.missing-path-argument",
                        message=f"path capability '{capability.value}' requires a bundled relative path argument",
                        recovery=f"Use {{{{forge:{capability.value}:path/to/file}}}}.",
                        capability=capability,
                    )
                )
                continue
            path_problem = _path_argument_problem(argument_value)
            if path_problem is not None:
                diagnostics.append(
                    SkillDiagnostic(
                        skill=source.manifest.name,
                        runtime=adapter.runtime,
                        path=path,
                        rule="template.invalid-path-argument",
                        message=f"path argument '{argument_value}' {path_problem}",
                        recovery="Use a normalized portable path to a file inside this skill package.",
                        capability=capability,
                    )
                )
                continue
            argument_path = PurePosixPath(argument_value)
            if argument_path not in available_paths:
                diagnostics.append(
                    SkillDiagnostic(
                        skill=source.manifest.name,
                        runtime=adapter.runtime,
                        path=path,
                        rule="template.missing-package-path",
                        message=f"path argument '{argument_value}' does not name an emitted source file",
                        recovery="Add the bundled file to SkillSource.files or correct the placeholder path.",
                        capability=capability,
                    )
                )
                continue
            if (
                binding is None
                or binding.relative_path_template is None
                or binding.relative_path_template.count("{path}") != 1
            ):
                diagnostics.append(
                    SkillDiagnostic(
                        skill=source.manifest.name,
                        runtime=adapter.runtime,
                        path=path,
                        rule="template.non-path-binding",
                        message=f"capability '{capability.value}' has no valid path-bearing {adapter.runtime.value} binding",
                        recovery="Add an evidence-backed relative_path_template containing exactly one {path} marker.",
                        capability=capability,
                    )
                )
            continue
        if argument_value is not None:
            diagnostics.append(
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=path,
                    rule="template.unexpected-argument",
                    message=f"capability '{capability.value}' does not accept a placeholder argument",
                    recovery=f"Use {{{{forge:{capability.value}}}}} without a trailing argument.",
                    capability=capability,
                )
            )
            continue
        if binding is None or binding.text is None:
            diagnostics.append(
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=path,
                    rule="template.non-textual-binding",
                    message=f"capability '{capability.value}' has no textual {adapter.runtime.value} binding",
                    recovery="Move this behavior into adapter structure or add an evidence-backed textual binding.",
                    capability=capability,
                )
            )

    # A partial or malformed marker is never treated as literal neutral content.
    recognized_spans = {match.span() for match in _PLACEHOLDER_CANDIDATE_RE.finditer(text)}
    for marker in re.finditer(r"\{\{forge:", text):
        if not any(start <= marker.start() < end for start, end in recognized_spans):
            diagnostics.append(
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=path,
                    rule="template.malformed-placeholder",
                    message="malformed Forge capability placeholder",
                    recovery=(
                        "Use {{forge:<capability-id>}} or "
                        "{{forge:<path-capability-id>:<portable-relative-path>}} on one line."
                    ),
                )
            )
    return diagnostics


def _render_template(
    content: bytes,
    source: SkillSource,
    adapter: SkillAdapter,
    path: PurePosixPath,
) -> bytes:
    # Validation has already established UTF-8 and complete textual bindings.
    text = content.decode("utf-8")

    def replace(match: re.Match[str]) -> str:
        capability = SkillCapability(match.group(1))
        binding = adapter.capability_bindings[capability]
        argument = match.group(2)
        if CAPABILITY_ARGUMENT_KINDS[capability] == CapabilityArgumentKind.RELATIVE_PATH:
            if argument is None or binding.relative_path_template is None:  # pragma: no cover - validated above
                raise AssertionError(f"missing relative path binding for {capability.value} in {path}")
            return binding.relative_path_template.replace("{path}", argument)
        if binding.text is None:  # pragma: no cover - guarded by _validate_placeholders
            raise AssertionError(f"missing textual binding for {capability.value} in {path}")
        return binding.text

    return _PLACEHOLDER_RE.sub(replace, text).encode("utf-8")


def _frontmatter_for(manifest: SkillManifest, runtime: SkillRuntime) -> dict[str, Any]:
    if runtime == SkillRuntime.CLAUDE_CODE:
        frontmatter: dict[str, Any] = {
            "name": f"forge:{manifest.name}",
            "description": manifest.description,
        }
        for key, value in manifest.claude_frontmatter.items():
            if key not in {"name", "description"}:
                frontmatter[key] = value
        if manifest.license is not None:
            frontmatter.setdefault("license", manifest.license)
        if manifest.compatibility is not None:
            frontmatter.setdefault("compatibility", manifest.compatibility)
        if manifest.metadata:
            frontmatter.setdefault("metadata", dict(manifest.metadata))
        if manifest.allowed_tools is not None:
            frontmatter.setdefault("allowed-tools", manifest.allowed_tools)
        if manifest.allow_implicit_invocation is not None:
            frontmatter["disable-model-invocation"] = not manifest.allow_implicit_invocation
        return frontmatter

    frontmatter = {
        "name": manifest.name,
        "description": manifest.description,
    }
    if manifest.license is not None:
        frontmatter["license"] = manifest.license
    if manifest.compatibility is not None:
        frontmatter["compatibility"] = manifest.compatibility
    if manifest.metadata:
        frontmatter["metadata"] = dict(manifest.metadata)
    if manifest.allowed_tools is not None:
        frontmatter["allowed-tools"] = manifest.allowed_tools
    return frontmatter


def _render_openai_yaml(manifest: SkillManifest) -> bytes | None:
    value: dict[str, Any] = {}
    interface = manifest.codex_interface
    if interface is not None:
        interface_value = {
            key: item
            for key, item in (
                ("display_name", interface.display_name),
                ("short_description", interface.short_description),
                ("icon_small", interface.icon_small),
                ("icon_large", interface.icon_large),
                ("brand_color", interface.brand_color),
                ("default_prompt", interface.default_prompt),
            )
            if item is not None
        }
        if interface_value:
            value["interface"] = interface_value
    if manifest.allow_implicit_invocation is not None:
        value["policy"] = {"allow_implicit_invocation": manifest.allow_implicit_invocation}
    if not value:
        return None
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=10_000,
    ).encode("utf-8")


def _render_skill_document(
    frontmatter: Mapping[str, Any],
    body: bytes,
    source: SkillSource,
    adapter: SkillAdapter,
) -> bytes:
    try:
        yaml_text = yaml.safe_dump(
            dict(frontmatter),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=10_000,
        )
    except yaml.YAMLError as exc:
        raise SkillCompilationError(
            [
                SkillDiagnostic(
                    skill=source.manifest.name,
                    runtime=adapter.runtime,
                    path=PurePosixPath("SKILL.md"),
                    rule="frontmatter.serialization",
                    message=f"frontmatter cannot be serialized safely: {exc}",
                    recovery="Use YAML-safe scalar values in manifest and adapter metadata.",
                    source_path=source.source_path,
                )
            ]
        ) from exc
    prefix = f"---\n{yaml_text}---\n".encode()
    if body and not body.startswith((b"\n", b"\r\n")):
        prefix += b"\n"
    return prefix + body


def _parse_skill_document(document: bytes, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label}: SKILL.md must be valid UTF-8") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError(f"{label}: SKILL.md must start with YAML frontmatter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        raise ValueError(f"{label}: SKILL.md has no closing YAML frontmatter delimiter")
    yaml_text = "".join(lines[1:closing_index])
    try:
        value = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{label}: malformed YAML frontmatter: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}: YAML frontmatter must be a mapping")
    return value, "".join(lines[closing_index + 1 :]).encode("utf-8")


def _required_manifest_string(manifest: Mapping[str, Any], key: str, manifest_path: Path) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{manifest_path}: {key} must be a non-empty string")
    return value


def _manifest_string_list(manifest: Mapping[str, Any], key: str, manifest_path: Path) -> list[str]:
    value = manifest.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{manifest_path}: {key} must be a list of non-empty strings")
    return value


def _manifest_enum_set(
    manifest: Mapping[str, Any],
    key: str,
    enum_type: type[_EnumT],
    manifest_path: Path,
    *,
    required: bool = False,
) -> set[_EnumT]:
    values = _manifest_string_list(manifest, key, manifest_path)
    if required and not values:
        raise ValueError(f"{manifest_path}: {key} must contain at least one value")
    parsed: list[_EnumT] = []
    for value in values:
        try:
            parsed.append(enum_type(value))
        except ValueError as exc:
            allowed = ", ".join(item.value for item in enum_type)
            raise ValueError(
                f"{manifest_path}: {key} contains unknown value {value!r}; expected one of {allowed}"
            ) from exc
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{manifest_path}: {key} contains duplicate values")
    return set(parsed)


def _is_skill_source_file(path: PurePosixPath) -> bool:
    if any(part.startswith(".") for part in path.parts):
        return False
    if _SKILL_SOURCE_EXCLUDED_DIRS & set(path.parts):
        return False
    return path.suffix not in _SKILL_SOURCE_EXCLUDED_SUFFIXES


def _read_contained_source_file(package_root: Path, source_file: Path) -> tuple[bytes, int]:
    if source_file.is_symlink():
        try:
            resolved = source_file.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"{source_file}: skill source symlink cannot be resolved: {exc}") from exc
        if not resolved.is_relative_to(package_root.resolve()) or not resolved.is_file():
            raise ValueError(f"{source_file}: skill source symlink must target a file inside its package")
    if not source_file.is_file():
        raise ValueError(f"{source_file}: skill source entries must be regular files")
    return source_file.read_bytes(), stat.S_IMODE(source_file.stat().st_mode)


def _path_argument_problem(raw: str) -> str | None:
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return "is absolute"
    if _PORTABLE_RELATIVE_PATH_RE.fullmatch(raw) is None:
        return "contains non-portable or unsafe characters"
    parts = raw.split("/")
    if any(part in {"", "."} for part in parts):
        return "is not normalized"
    if ".." in parts:
        return "escapes the skill package"
    return None


def _runtime_exclusion_path_problem(raw: str) -> str | None:
    problem = _path_argument_problem(raw)
    if problem is not None:
        return problem
    path = PurePosixPath(raw)
    if path in _COMPILER_OWNED_SOURCE_PATHS:
        return "targets a compiler-owned source document"
    if not path.parts or path.parts[0] != "references" or path.suffix.lower() not in {".md", ".markdown"}:
        return "is not a Markdown documentary auxiliary under references/"
    return None


def _source_path_problem(path: PurePosixPath) -> str | None:
    raw = path.as_posix()
    if not raw or raw == ".":
        return "package path is empty"
    if path.is_absolute() or raw.startswith("/"):
        return "package path is absolute"
    if "\\" in raw:
        return "package path contains a non-POSIX separator"
    if any(part in {"", ".", ".."} for part in path.parts):
        return "package path is not normalized or escapes the package root"
    if path == PurePosixPath("SKILL.md"):
        return "auxiliary files may not replace compiler-owned SKILL.md"
    return None


def _with_source_path(
    diagnostics: tuple[SkillDiagnostic, ...] | list[SkillDiagnostic],
    source_path: str | None,
) -> tuple[SkillDiagnostic, ...]:
    if source_path is None:
        return tuple(diagnostics)
    return tuple(
        diagnostic if diagnostic.source_path is not None else replace(diagnostic, source_path=source_path)
        for diagnostic in diagnostics
    )


__all__ = [
    "CLAUDE_SKILL_ADAPTER",
    "CODEX_SKILL_ADAPTER",
    "CAPABILITY_ARGUMENT_KINDS",
    "NEUTRAL_SKILL_CONTENT",
    "NEUTRAL_SKILL_MANIFEST",
    "NEUTRAL_SKILL_SCHEMA_VERSION",
    "CapabilityArgumentKind",
    "CapabilityBinding",
    "CodexSkillInterface",
    "CompiledSkillFile",
    "CompiledSkillPackage",
    "SkillAdapter",
    "SkillCapability",
    "SkillCompilationError",
    "SkillDiagnostic",
    "SkillManifest",
    "SkillRuntime",
    "SkillSource",
    "SkillSourceFile",
    "SkillSourceFormat",
    "TokenAllowance",
    "adapter_for_runtime",
    "compile_skill",
    "compile_skill_for_runtime",
    "load_claude_skill_source",
    "load_claude_skill_sources",
    "load_neutral_skill_source",
    "load_skill_source",
    "load_skill_sources",
]
