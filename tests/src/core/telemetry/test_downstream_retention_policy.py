"""Resolution and migration tests for the single downstream-retention owner."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

from forge.core.telemetry import downstream_retention as retention
from forge.core.telemetry.downstream_retention import (
    DEFAULT_MAX_TOTAL_MB,
    DEFAULT_RETENTION_DAYS,
    DownstreamRetentionMigrationError,
    DownstreamRetentionPolicy,
    apply_downstream_retention_migration,
    plan_downstream_retention_migration,
    resolve_downstream_retention,
)


def _write_yaml(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _proxy(proxies_dir: Path, proxy_id: str, **sections: Any) -> Path:
    return _write_yaml(
        proxies_dir / proxy_id / "proxy.yaml",
        {
            "proxy_format": 1,
            "template": "openrouter-anthropic",
            "tiers": {"sonnet": "anthropic/claude-sonnet-4-6"},
            **sections,
        },
    )


def test_no_global_or_legacy_values_uses_defaults(tmp_path: Path) -> None:
    resolution = resolve_downstream_retention(
        runtime_config_path=tmp_path / "config.yaml",
        proxies_dir=tmp_path / "proxies",
    )

    assert resolution.configured is None
    assert resolution.effective == DownstreamRetentionPolicy(DEFAULT_RETENTION_DAYS, DEFAULT_MAX_TOTAL_MB)
    assert resolution.source == "default"
    assert resolution.to_dict()["degraded"] is False
    assert resolution.deprecated_keys == ()


@pytest.mark.parametrize("content", ["", "# no runtime overrides\n"])
def test_empty_runtime_config_uses_defaults(tmp_path: Path, content: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content)

    resolution = resolve_downstream_retention(
        runtime_config_path=config_path,
        proxies_dir=tmp_path / "proxies",
    )

    assert resolution.effective == DownstreamRetentionPolicy(DEFAULT_RETENTION_DAYS, DEFAULT_MAX_TOTAL_MB)
    assert resolution.source == "default"
    assert resolution.errors == ()


@pytest.mark.parametrize("content", ["null\n", "42\n", "[]\n"])
def test_non_mapping_runtime_document_fails_closed(tmp_path: Path, content: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content)

    resolution = resolve_downstream_retention(
        runtime_config_path=config_path,
        proxies_dir=tmp_path / "proxies",
    )

    assert not resolution.pruning_enabled
    assert resolution.errors[0].detail == "root must be a mapping"


def test_non_directory_proxy_config_path_disables_pruning(tmp_path: Path) -> None:
    proxies_path = tmp_path / "proxies"
    proxies_path.write_text("not a directory")

    resolution = resolve_downstream_retention(
        runtime_config_path=tmp_path / "config.yaml",
        proxies_dir=proxies_path,
    )

    assert not resolution.pruning_enabled
    assert resolution.errors[0].path == str(proxies_path)


def test_partial_explicit_global_wins_and_reports_legacy_replacements(
    tmp_path: Path,
) -> None:
    config_path = _write_yaml(tmp_path / "config.yaml", {"telemetry": {"downstream": {"retention_days": 0}}})
    proxies_dir = tmp_path / "proxies"
    _proxy(proxies_dir, "alpha", audit={"retention_days": 90, "max_total_mb": 128})
    _proxy(proxies_dir, "beta", provider_trace={"retention_days": 14, "max_total_mb": 256})

    resolution = resolve_downstream_retention(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert resolution.source == "global"
    assert resolution.configured is not None
    assert resolution.configured.retention_days == 0
    assert resolution.configured.max_total_mb is None
    assert resolution.effective == DownstreamRetentionPolicy(0, DEFAULT_MAX_TOTAL_MB)
    assert {item.proxy_id for item in resolution.deprecated_keys} == {"alpha", "beta"}
    assert {item.replacement for item in resolution.deprecated_keys} == {
        "telemetry.downstream.retention_days",
        "telemetry.downstream.max_total_mb",
    }


def test_matching_explicit_legacy_values_resolve_as_consensus(tmp_path: Path) -> None:
    proxies_dir = tmp_path / "proxies"
    _proxy(proxies_dir, "alpha", audit={"retention_days": 30})
    _proxy(proxies_dir, "beta", provider_trace={"retention_days": 30, "max_total_mb": 768})
    _proxy(proxies_dir, "omitted", audit={"audit_full_body": False})

    resolution = resolve_downstream_retention(
        runtime_config_path=tmp_path / "config.yaml",
        proxies_dir=proxies_dir,
    )

    assert resolution.effective == DownstreamRetentionPolicy(30, 768)
    assert resolution.source == "legacy_consensus"
    assert resolution.conflicts == ()
    assert {item.proxy_id for item in resolution.deprecated_keys} == {"alpha", "beta"}


def test_conflicting_legacy_values_disable_pruning_and_name_proxies(
    tmp_path: Path,
) -> None:
    proxies_dir = tmp_path / "proxies"
    _proxy(proxies_dir, "alpha", audit={"retention_days": 90})
    _proxy(proxies_dir, "beta", provider_trace={"retention_days": 14})

    resolution = resolve_downstream_retention(
        runtime_config_path=tmp_path / "config.yaml",
        proxies_dir=proxies_dir,
    )

    assert resolution.effective is None
    assert resolution.source is None
    assert not resolution.pruning_enabled
    assert resolution.to_dict()["degraded"] is True
    assert len(resolution.conflicts) == 1
    assert resolution.conflicts[0].field == "retention_days"
    assert {proxy for value in resolution.conflicts[0].values for proxy in value.proxy_ids} == {"alpha", "beta"}


@pytest.mark.parametrize(
    "document",
    [
        {"telemetry": {"downstream": {"retention_days": True}}},
        {"telemetry": {"downstream": {"max_total_mb": -1}}},
        {"telemetry": {"downstream": {"unexpected": 1}}},
        {"telemetry": {"downstream": "fourteen"}},
    ],
)
def test_malformed_explicit_global_policy_fails_closed(tmp_path: Path, document: dict[str, Any]) -> None:
    config_path = _write_yaml(tmp_path / "config.yaml", document)

    resolution = resolve_downstream_retention(runtime_config_path=config_path, proxies_dir=tmp_path / "proxies")

    assert resolution.effective is None
    assert resolution.source is None
    assert resolution.errors


def test_consensus_migration_writes_owner_then_removes_only_legacy_keys(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    proxies_dir = tmp_path / "proxies"
    proxy_path = _proxy(
        proxies_dir,
        "alpha",
        audit={"audit_full_body": True, "retention_days": 45, "max_total_mb": 640},
        provider_trace={"retention_days": 45, "max_total_mb": 640},
    )
    proxy_path.chmod(0o640)

    result = apply_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert result.wrote_global_policy is True
    assert result.migrated_proxy_ids == ("alpha",)
    assert yaml.safe_load(config_path.read_text())["telemetry"]["downstream"] == {
        "retention_days": 45,
        "max_total_mb": 640,
    }
    migrated = yaml.safe_load(proxy_path.read_text())
    assert migrated["audit"] == {"audit_full_body": True}
    assert "provider_trace" not in migrated
    assert stat.S_IMODE(proxy_path.stat().st_mode) == 0o640


def test_conflict_blocks_migration_without_mutating_files(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    proxies_dir = tmp_path / "proxies"
    alpha = _proxy(proxies_dir, "alpha", audit={"retention_days": 90})
    beta = _proxy(proxies_dir, "beta", provider_trace={"retention_days": 14})
    before = {alpha: alpha.read_bytes(), beta: beta.read_bytes()}

    plan = plan_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert plan.blocked
    with pytest.raises(DownstreamRetentionMigrationError, match="blocked"):
        apply_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)
    assert not config_path.exists()
    assert {path: path.read_bytes() for path in before} == before


def test_partial_migration_is_coherent_and_rerunnable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    proxies_dir = tmp_path / "proxies"
    alpha = _proxy(proxies_dir, "alpha", audit={"retention_days": 21, "max_total_mb": 300})
    beta = _proxy(proxies_dir, "beta", provider_trace={"retention_days": 21, "max_total_mb": 300})
    real_remove = retention._remove_migrated_proxy_keys

    def fail_second(target: retention.RetentionMigrationTarget) -> None:
        if target.proxy_id == "beta":
            raise OSError("injected migration fault")
        real_remove(target)

    monkeypatch.setattr(retention, "_remove_migrated_proxy_keys", fail_second)
    with pytest.raises(OSError, match="injected migration fault"):
        apply_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert yaml.safe_load(config_path.read_text())["telemetry"]["downstream"] == {
        "retention_days": 21,
        "max_total_mb": 300,
    }
    assert "audit" not in yaml.safe_load(alpha.read_text())
    assert "retention_days" in yaml.safe_load(beta.read_text())["provider_trace"]

    monkeypatch.setattr(retention, "_remove_migrated_proxy_keys", real_remove)
    rerun = apply_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert rerun.wrote_global_policy is False
    assert rerun.migrated_proxy_ids == ("beta",)
    assert "provider_trace" not in yaml.safe_load(beta.read_text())


def test_migration_blocks_when_global_is_valid_but_a_proxy_is_unreadable(
    tmp_path: Path,
) -> None:
    config_path = _write_yaml(
        tmp_path / "config.yaml",
        {"telemetry": {"downstream": {"retention_days": 14, "max_total_mb": 512}}},
    )
    proxies_dir = tmp_path / "proxies"
    broken = proxies_dir / "broken" / "proxy.yaml"
    broken.parent.mkdir(parents=True)
    broken.write_text("audit: [unterminated")

    plan = plan_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    assert plan.resolution.pruning_enabled
    assert plan.resolution.source == "global"
    assert plan.resolution.errors
    assert plan.blocked


def test_migration_does_not_overwrite_a_concurrent_global_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    proxies_dir = tmp_path / "proxies"
    _proxy(proxies_dir, "alpha", audit={"retention_days": 30, "max_total_mb": 600})
    real_write = retention._write_global_policy

    def inject_global_choice(path: Path, policy: DownstreamRetentionPolicy) -> None:
        _write_yaml(
            path,
            {
                "proxy_mode": "sidecar",
                "telemetry": {"downstream": {"retention_days": 90, "max_total_mb": 900}},
            },
        )
        real_write(path, policy)

    monkeypatch.setattr(retention, "_write_global_policy", inject_global_choice)

    with pytest.raises(DownstreamRetentionMigrationError, match="changed before migration"):
        apply_downstream_retention_migration(runtime_config_path=config_path, proxies_dir=proxies_dir)

    configured = yaml.safe_load(config_path.read_text())
    assert configured["proxy_mode"] == "sidecar"
    assert configured["telemetry"]["downstream"] == {
        "retention_days": 90,
        "max_total_mb": 900,
    }
    proxy = yaml.safe_load((proxies_dir / "alpha" / "proxy.yaml").read_text())
    assert proxy["audit"]["retention_days"] == 30
