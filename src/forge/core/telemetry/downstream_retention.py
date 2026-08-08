"""Single-owner policy resolution for shared downstream telemetry retention.

Audit, cost, and provider-lifecycle records coexist in one shard directory. This module
resolves one global policy, treats the former proxy-local settings as migration inputs,
and blocks automatic pruning when legacy inputs disagree or cannot be inspected safely.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Any, Literal

import yaml

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_text
from forge.runtime_config import (
    DEFAULT_DOWNSTREAM_MAX_TOTAL_MB,
    DEFAULT_DOWNSTREAM_RETENTION_DAYS,
)

DEFAULT_RETENTION_DAYS = DEFAULT_DOWNSTREAM_RETENTION_DAYS
DEFAULT_MAX_TOTAL_MB = DEFAULT_DOWNSTREAM_MAX_TOTAL_MB
GLOBAL_RETENTION_PATH = "telemetry.downstream"

RetentionSource = Literal["global", "legacy_consensus", "default"]


@dataclass(frozen=True)
class DownstreamRetentionPolicy:
    retention_days: int
    max_total_mb: int


@dataclass(frozen=True)
class ConfiguredDownstreamRetention:
    retention_days: int | None
    max_total_mb: int | None


@dataclass(frozen=True)
class DeprecatedRetentionKey:
    proxy_id: str
    proxy_path: str
    key: str
    value: int
    replacement: str


@dataclass(frozen=True)
class RetentionConflictValue:
    value: int
    proxy_ids: tuple[str, ...]
    keys: tuple[str, ...]


@dataclass(frozen=True)
class RetentionConflict:
    field: str
    values: tuple[RetentionConflictValue, ...]


@dataclass(frozen=True)
class RetentionConfigError:
    scope: str
    path: str
    detail: str
    proxy_id: str | None = None


@dataclass(frozen=True)
class DownstreamRetentionResolution:
    configured: ConfiguredDownstreamRetention | None
    effective: DownstreamRetentionPolicy | None
    source: RetentionSource | None
    deprecated_keys: tuple[DeprecatedRetentionKey, ...] = ()
    conflicts: tuple[RetentionConflict, ...] = ()
    errors: tuple[RetentionConfigError, ...] = ()

    @property
    def pruning_enabled(self) -> bool:
        return self.effective is not None and self.source is not None

    @property
    def degraded(self) -> bool:
        return not self.pruning_enabled

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": asdict(self.configured) if self.configured is not None else None,
            "effective": asdict(self.effective) if self.effective is not None else None,
            "source": self.source,
            "pruning_enabled": self.pruning_enabled,
            "degraded": self.degraded,
            "deprecated_keys": [asdict(item) for item in self.deprecated_keys],
            "conflicts": [asdict(item) for item in self.conflicts],
            "errors": [asdict(item) for item in self.errors],
        }


@dataclass(frozen=True)
class RetentionMigrationTarget:
    proxy_id: str
    proxy_path: str
    keys: tuple[DeprecatedRetentionKey, ...]


@dataclass(frozen=True)
class DownstreamRetentionMigrationPlan:
    resolution: DownstreamRetentionResolution
    runtime_config_path: str
    write_global_policy: bool
    targets: tuple[RetentionMigrationTarget, ...]

    @property
    def blocked(self) -> bool:
        # A valid explicit global policy is sufficient for startup pruning, but
        # migration must inspect every file it proposes to rewrite. Do not claim
        # migration completeness while any proxy config is unreadable.
        return not self.resolution.pruning_enabled or bool(self.resolution.errors)

    @property
    def has_changes(self) -> bool:
        return self.write_global_policy or bool(self.targets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "has_changes": self.has_changes,
            "write_global_policy": self.write_global_policy,
            "runtime_config_path": self.runtime_config_path,
            "targets": [
                {
                    "proxy_id": target.proxy_id,
                    "proxy_path": target.proxy_path,
                    "keys": [item.key for item in target.keys],
                }
                for target in self.targets
            ],
            "resolution": self.resolution.to_dict(),
        }


@dataclass(frozen=True)
class DownstreamRetentionMigrationResult:
    wrote_global_policy: bool
    migrated_proxy_ids: tuple[str, ...]


class DownstreamRetentionMigrationError(RuntimeError):
    """The explicit migration could not preserve a coherent global policy."""


def _runtime_config_path() -> Path:
    return get_forge_home() / "config.yaml"


def _proxy_config_dir() -> Path:
    return get_forge_home() / "proxies"


def _validate_bound(value: Any, *, key: str, allow_zero: bool) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{key} must be a {qualifier} int")
    return value


def _read_global_retention(
    config_path: Path,
) -> tuple[
    ConfiguredDownstreamRetention | None,
    DownstreamRetentionPolicy | None,
    list[RetentionConfigError],
]:
    try:
        config_mode = config_path.stat().st_mode
    except FileNotFoundError:
        return None, None, []
    except OSError as exc:
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), f"could not inspect file: {exc}")],
        )
    if not S_ISREG(config_mode):
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), "path is not a regular file")],
        )

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        empty_document = data is None and yaml.compose(raw) is None
    except Exception as exc:
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), f"could not read YAML: {exc}")],
        )
    if empty_document:
        # Empty and comment-only YAML are valid ways to express no overrides.
        return None, None, []
    if not isinstance(data, Mapping):
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), "root must be a mapping")],
        )

    telemetry = data.get("telemetry")
    if telemetry is None:
        return None, None, []
    if not isinstance(telemetry, Mapping):
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), "telemetry must be a mapping")],
        )

    downstream = telemetry.get("downstream")
    if downstream is None:
        return None, None, []
    if not isinstance(downstream, Mapping):
        return (
            None,
            None,
            [RetentionConfigError("global", str(config_path), "telemetry.downstream must be a mapping")],
        )

    known = {"retention_days", "max_total_mb"}
    unknown = sorted(str(key) for key in downstream if key not in known)
    if unknown:
        return (
            None,
            None,
            [
                RetentionConfigError(
                    "global",
                    str(config_path),
                    f"unknown telemetry.downstream key(s): {', '.join(unknown)}",
                )
            ],
        )

    has_days = "retention_days" in downstream
    has_size = "max_total_mb" in downstream
    if not has_days and not has_size:
        return None, None, []

    try:
        configured_days = (
            _validate_bound(
                downstream["retention_days"],
                key="telemetry.downstream.retention_days",
                allow_zero=True,
            )
            if has_days
            else None
        )
        configured_size = (
            _validate_bound(
                downstream["max_total_mb"],
                key="telemetry.downstream.max_total_mb",
                allow_zero=True,
            )
            if has_size
            else None
        )
    except ValueError as exc:
        return None, None, [RetentionConfigError("global", str(config_path), str(exc))]

    configured = ConfiguredDownstreamRetention(configured_days, configured_size)
    effective = DownstreamRetentionPolicy(
        retention_days=configured_days if configured_days is not None else DEFAULT_RETENTION_DAYS,
        max_total_mb=configured_size if configured_size is not None else DEFAULT_MAX_TOTAL_MB,
    )
    return configured, effective, []


def _read_legacy_retention(
    proxies_dir: Path,
) -> tuple[list[DeprecatedRetentionKey], list[RetentionConfigError]]:
    deprecated: list[DeprecatedRetentionKey] = []
    errors: list[RetentionConfigError] = []
    try:
        proxies_mode = proxies_dir.stat().st_mode
    except FileNotFoundError:
        return deprecated, errors
    except OSError as exc:
        return deprecated, [
            RetentionConfigError("proxy", str(proxies_dir), f"could not inspect proxy directory: {exc}")
        ]
    if not S_ISDIR(proxies_mode):
        return deprecated, [
            RetentionConfigError("proxy", str(proxies_dir), "proxy configuration path is not a directory")
        ]
    try:
        candidates = sorted(proxies_dir.glob("*/proxy.yaml"))
    except OSError as exc:
        return deprecated, [
            RetentionConfigError("proxy", str(proxies_dir), f"could not enumerate proxy configs: {exc}")
        ]
    if not candidates:
        return deprecated, errors

    for proxy_path in candidates:
        proxy_id = proxy_path.parent.name
        try:
            data = yaml.safe_load(proxy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(
                RetentionConfigError(
                    "proxy",
                    str(proxy_path),
                    f"could not read YAML: {exc}",
                    proxy_id=proxy_id,
                )
            )
            continue
        if not isinstance(data, Mapping):
            errors.append(
                RetentionConfigError(
                    "proxy",
                    str(proxy_path),
                    "root must be a mapping",
                    proxy_id=proxy_id,
                )
            )
            continue

        for section_name in ("audit", "provider_trace"):
            section = data.get(section_name)
            if section is None:
                continue
            if not isinstance(section, Mapping):
                errors.append(
                    RetentionConfigError(
                        "proxy",
                        str(proxy_path),
                        f"{section_name} must be a mapping",
                        proxy_id=proxy_id,
                    )
                )
                continue
            for field_name in ("retention_days", "max_total_mb"):
                if field_name not in section:
                    continue
                key = f"{section_name}.{field_name}"
                try:
                    value = _validate_bound(
                        section[field_name],
                        key=key,
                        allow_zero=field_name == "retention_days",
                    )
                except ValueError as exc:
                    errors.append(RetentionConfigError("proxy", str(proxy_path), str(exc), proxy_id=proxy_id))
                    continue
                deprecated.append(
                    DeprecatedRetentionKey(
                        proxy_id=proxy_id,
                        proxy_path=str(proxy_path),
                        key=key,
                        value=value,
                        replacement=f"{GLOBAL_RETENTION_PATH}.{field_name}",
                    )
                )

    return deprecated, errors


def _legacy_conflicts(
    deprecated: list[DeprecatedRetentionKey],
) -> tuple[RetentionConflict, ...]:
    by_field: dict[str, dict[int, list[DeprecatedRetentionKey]]] = {
        "retention_days": defaultdict(list),
        "max_total_mb": defaultdict(list),
    }
    for item in deprecated:
        field_name = item.key.rsplit(".", 1)[-1]
        by_field[field_name][item.value].append(item)

    conflicts: list[RetentionConflict] = []
    for field_name, values in by_field.items():
        if len(values) <= 1:
            continue
        conflict_values = []
        for value, items in sorted(values.items()):
            conflict_values.append(
                RetentionConflictValue(
                    value=value,
                    proxy_ids=tuple(sorted({item.proxy_id for item in items})),
                    keys=tuple(sorted({item.key for item in items})),
                )
            )
        conflicts.append(RetentionConflict(field_name, tuple(conflict_values)))
    return tuple(conflicts)


def resolve_downstream_retention(
    *,
    runtime_config_path: Path | None = None,
    proxies_dir: Path | None = None,
) -> DownstreamRetentionResolution:
    """Resolve the one effective downstream policy from global and compatibility inputs."""
    config_path = runtime_config_path or _runtime_config_path()
    proxy_root = proxies_dir or _proxy_config_dir()
    configured, global_policy, global_errors = _read_global_retention(config_path)
    deprecated, proxy_errors = _read_legacy_retention(proxy_root)

    # An explicit, valid global policy always wins. Legacy parse failures cannot
    # make that policy ambiguous, but remain visible for migration/recovery.
    if global_policy is not None:
        return DownstreamRetentionResolution(
            configured=configured,
            effective=global_policy,
            source="global",
            deprecated_keys=tuple(deprecated),
            errors=tuple(proxy_errors),
        )

    errors = tuple([*global_errors, *proxy_errors])
    conflicts = _legacy_conflicts(deprecated)
    if errors or conflicts:
        return DownstreamRetentionResolution(
            configured=None,
            effective=None,
            source=None,
            deprecated_keys=tuple(deprecated),
            conflicts=conflicts,
            errors=errors,
        )

    if deprecated:
        values: dict[str, int] = {}
        for item in deprecated:
            values[item.key.rsplit(".", 1)[-1]] = item.value
        return DownstreamRetentionResolution(
            configured=None,
            effective=DownstreamRetentionPolicy(
                retention_days=values.get("retention_days", DEFAULT_RETENTION_DAYS),
                max_total_mb=values.get("max_total_mb", DEFAULT_MAX_TOTAL_MB),
            ),
            source="legacy_consensus",
            deprecated_keys=tuple(deprecated),
        )

    return DownstreamRetentionResolution(
        configured=None,
        effective=DownstreamRetentionPolicy(DEFAULT_RETENTION_DAYS, DEFAULT_MAX_TOTAL_MB),
        source="default",
    )


def plan_downstream_retention_migration(
    *,
    runtime_config_path: Path | None = None,
    proxies_dir: Path | None = None,
) -> DownstreamRetentionMigrationPlan:
    config_path = runtime_config_path or _runtime_config_path()
    resolution = resolve_downstream_retention(runtime_config_path=config_path, proxies_dir=proxies_dir)
    grouped: dict[tuple[str, str], list[DeprecatedRetentionKey]] = defaultdict(list)
    for item in resolution.deprecated_keys:
        grouped[(item.proxy_id, item.proxy_path)].append(item)
    targets = tuple(
        RetentionMigrationTarget(proxy_id, proxy_path, tuple(sorted(items, key=lambda item: item.key)))
        for (proxy_id, proxy_path), items in sorted(grouped.items())
    )
    return DownstreamRetentionMigrationPlan(
        resolution=resolution,
        runtime_config_path=str(config_path),
        write_global_policy=resolution.source == "legacy_consensus",
        targets=targets,
    )


def _write_global_policy(path: Path, policy: DownstreamRetentionPolicy) -> None:
    from ruamel.yaml import YAML

    from forge.runtime_config import write_runtime_config

    ruamel = YAML()
    ruamel.preserve_quotes = True
    try:
        if path.is_file():
            with open(path, encoding="utf-8") as stream:
                data = ruamel.load(stream) or {}
        else:
            data = {}
    except OSError:
        raise
    except Exception as exc:
        raise DownstreamRetentionMigrationError(f"Runtime config changed before migration: {path}: {exc}") from exc
    if not isinstance(data, MutableMapping):
        raise DownstreamRetentionMigrationError(f"Runtime config root is not a mapping: {path}")
    telemetry = data.get("telemetry")
    if telemetry is None:
        telemetry = {}
        data["telemetry"] = telemetry
    elif not isinstance(telemetry, MutableMapping):
        raise DownstreamRetentionMigrationError(f"Runtime config changed before migration at telemetry: {path}")
    downstream = telemetry.get("downstream")
    if downstream is None:
        downstream = {}
        telemetry["downstream"] = downstream
    elif not isinstance(downstream, MutableMapping) or downstream:
        # The plan reached this writer only when no global policy existed. A
        # non-empty block now means the operator made a concurrent choice; never
        # overwrite it with the earlier legacy consensus.
        raise DownstreamRetentionMigrationError(
            f"Runtime config changed before migration at {GLOBAL_RETENTION_PATH}: {path}"
        )
    downstream.update(asdict(policy))
    write_runtime_config(data, path=path)


def _remove_migrated_proxy_keys(target: RetentionMigrationTarget) -> None:
    from ruamel.yaml import YAML

    path = Path(target.proxy_path)
    ruamel = YAML()
    ruamel.preserve_quotes = True
    try:
        with open(path, encoding="utf-8") as stream:
            data = ruamel.load(stream)
    except OSError:
        raise
    except Exception as exc:
        raise DownstreamRetentionMigrationError(
            f"{target.proxy_id} changed before migration and is no longer valid YAML: {path}: {exc}"
        ) from exc
    if not isinstance(data, MutableMapping):
        raise DownstreamRetentionMigrationError(f"Proxy config root changed before migration: {path}")

    for item in target.keys:
        section_name, field_name = item.key.split(".", 1)
        section = data.get(section_name)
        current = section.get(field_name) if isinstance(section, Mapping) else None
        if isinstance(current, bool) or not isinstance(current, int) or current != item.value:
            raise DownstreamRetentionMigrationError(
                f"{target.proxy_id} changed before migration at {item.key}; no keys were removed from this file"
            )

    for item in target.keys:
        section_name, field_name = item.key.split(".", 1)
        section = data[section_name]
        if not isinstance(section, MutableMapping):  # proved above; keeps the mutation boundary explicit
            raise DownstreamRetentionMigrationError(f"{target.proxy_id} changed before migration at {item.key}")
        del section[field_name]
        if not section:
            del data[section_name]

    rendered = StringIO()
    ruamel.dump(data, rendered)
    atomic_write_text(path, rendered.getvalue(), preserve_existing_mode=True, create_parents=False)


def apply_downstream_retention_migration(
    *,
    runtime_config_path: Path | None = None,
    proxies_dir: Path | None = None,
) -> DownstreamRetentionMigrationResult:
    """Write the authoritative global policy first, then remove matching legacy keys.

    Writing the owner first keeps partial failures coherent: any proxy file left with
    compatibility keys is ignored under the already-persisted global policy, and rerunning
    the same command removes the remaining keys.
    """
    plan = plan_downstream_retention_migration(runtime_config_path=runtime_config_path, proxies_dir=proxies_dir)
    if plan.blocked or plan.resolution.effective is None:
        raise DownstreamRetentionMigrationError(
            "Retention migration is blocked by conflicting or unreadable configuration; "
            "repair invalid inputs or choose telemetry.downstream explicitly, then rerun"
        )

    config_path = Path(plan.runtime_config_path)
    if plan.write_global_policy:
        _write_global_policy(config_path, plan.resolution.effective)

    migrated: list[str] = []
    for target in plan.targets:
        _remove_migrated_proxy_keys(target)
        migrated.append(target.proxy_id)
    return DownstreamRetentionMigrationResult(plan.write_global_policy, tuple(migrated))
