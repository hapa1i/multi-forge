"""Execute only the separately approved, fixed disposable Claude layout probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

APPROVED_MANIFEST_SHA256 = "c56029340ddcdf37ef9ef414b10bcf22a91cedef05d5a9a2f9f2b8ee876c4dde"
COMPANION_MANIFEST_SHA256 = "20f0af8172af71995d463ff03efa7292d0e9c0b752b379c500d750d3ebea38d1"
SCRIPT_ROOT = Path(__file__).resolve().parent
REPOSITORY = SCRIPT_ROOT.parents[2]
PYTHON = "/forge/.venv/bin/python"


def load_manifest(path: Path) -> dict[str, Any]:
    """Bind execution to the exact user-approved bytes, including every argument."""
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() not in {APPROVED_MANIFEST_SHA256, COMPANION_MANIFEST_SHA256}:
        raise ValueError("This runner accepts only the exact approved native-probe manifest")
    return json.loads(data)


def container_argv(manifest: dict[str, Any]) -> list[str]:
    """Create an isolated container without host mounts or persisted credentials."""
    result = [
        "docker",
        "create",
        "--name",
        manifest["container_name"],
        "--workdir",
        manifest["container_workspace"],
    ]
    for key, value in manifest["container_environment"].items():
        result.extend(["--env", f"{key}={value}"])
    return [*result, manifest["image"], "sleep", "infinity"]


def run_probe(manifest_path: Path, output: Path) -> None:
    """Run offline gates, then at most one authorized native inference invocation."""
    manifest = load_manifest(manifest_path)
    if manifest.get("payload_sha256") and manifest["payload_sha256"] != _sha(SCRIPT_ROOT / "native_probe_payload.py"):
        raise ValueError("Probe payload changed since the manifest was prepared; approval must be refreshed")
    if not output.is_absolute() or output.exists() or ".." in output.parts:
        raise ValueError("Output must be a new absolute directory without parent traversal")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is absent; no login fallback is permitted")
    name = manifest["container_name"]
    _command(["docker", "version", "--format", "{{.Server.Version}}"])
    names = _command(["docker", "container", "ls", "-a", "--format", "{{.Names}}"])
    if name in names.splitlines():
        raise ValueError(f"Refusing existing container {name}")
    output.mkdir(parents=True)
    (output / "approved-manifest.json").write_bytes(manifest_path.read_bytes())
    metadata: dict[str, Any] = {
        "approved_manifest_sha256": _sha(manifest_path),
        "runner_sha256": _sha(Path(__file__)),
        "payload_sha256": _sha(SCRIPT_ROOT / "native_probe_payload.py"),
        "generator_sha256": _sha(SCRIPT_ROOT / "native-probe-manifest.py"),
        "status": "offline_preflight",
        "native_invocations_dispatched": 0,
        "host_mounts": [],
        "auth_forwarded_by_name": ["ANTHROPIC_API_KEY"],
    }
    created = False
    exported = False
    try:
        _command(manifest["build_argv"], output / "build.log", timeout=1800)
        metadata["image_id"] = _command(
            ["docker", "image", "inspect", manifest["image"], "--format", "{{.Id}}"]
        ).strip()
        metadata["container_id"] = _command(container_argv(manifest)).strip()
        created = True
        _command(["docker", "start", name])
        _command(["docker", "exec", name, "mkdir", "-p", "/probe/home", "/probe/workspace", "/probe/evidence"])
        for source, target in (
            (manifest_path, "/probe/manifest.json"),
            (SCRIPT_ROOT / "native_probe_payload.py", "/probe/native_probe_payload.py"),
        ):
            _command(["docker", "cp", str(source), f"{name}:{target}"])
        _command(
            ["docker", "exec", name, PYTHON, "/probe/native_probe_payload.py", "preflight"],
            output / "preflight.log",
        )
        _command(
            [
                "docker",
                "exec",
                "--workdir",
                "/forge",
                "--env",
                "CLAUDE_CONFIG_DIR=",
                name,
                PYTHON,
                "-m",
                "pytest",
                "-q",
                "tests/integration/docker/test_session_delete_purge_lifecycle.py",
                "tests/regression/test_bug_deleted_session_artifact_writer.py",
            ],
            output / "offline-docker-tests.log",
            timeout=120,
        )
        metadata["status"] = "native_dispatched_no_retry"
        metadata["native_invocations_dispatched"] = 1
        _save(output / "execution.json", metadata)
        # The marker is durable before dispatch: a timeout or unknown outcome never permits a retry.
        _command(
            ["docker", "exec", "--env", "ANTHROPIC_API_KEY", name, PYTHON, "/probe/native_probe_payload.py", "run"],
            output / "probe.log",
            timeout=manifest["wall_seconds"] + 30,
        )
        metadata["status"] = "completed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        metadata["status"] = "failed_no_retry"
        metadata["error"] = _redact(str(error))
        raise
    finally:
        cleanup_errors: list[str] = []
        removed = False
        if created:
            try:
                _command(["docker", "cp", f"{name}:/probe/evidence", str(output / "container-evidence")])
                if manifest.get("probe_kind") == "companion_metadata_only":
                    verify_export(output / "container-evidence")
                exported = True
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                cleanup_errors.append(_redact(str(error)))
            if manifest.get("probe_kind") == "companion_metadata_only":
                # Preserve captured evidence in the stopped container but remove all runtime auth/config state.
                try:
                    _command(
                        [
                            "docker",
                            "exec",
                            name,
                            PYTHON,
                            "-c",
                            "import shutil; shutil.rmtree('/probe/home', ignore_errors=True)",
                        ]
                    )
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    cleanup_errors.append(_redact(str(error)))
            try:
                _command(["docker", "stop", "--time", "5", name])
                remove = exported and (
                    manifest.get("probe_kind") != "companion_metadata_only" or metadata["status"] == "completed"
                )
                if remove and not cleanup_errors:
                    _command(["docker", "rm", name])
                    removed = True
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                cleanup_errors.append(_redact(str(error)))
        metadata["evidence_exported"] = exported
        metadata["container_removed"] = removed
        metadata["cleanup_errors"] = cleanup_errors
        _save(output / "execution.json", metadata)
    if cleanup_errors:
        raise ValueError("Probe evidence export or container cleanup needs attention; no inference retry")


def verify_export(directory: Path) -> None:
    """Check every captured evidence byte before removing the disposable container."""
    inventory = json.loads((directory / "export-inventory.json").read_text())
    if not isinstance(inventory, dict) or "native-result.json" not in inventory:
        raise ValueError("Incomplete exported evidence inventory")
    for relative, digest in inventory.items():
        path = directory / relative
        if (
            not path.is_relative_to(directory)
            or ".." in Path(relative).parts
            or path.is_symlink()
            or _sha(path) != digest
        ):
            raise ValueError(f"Exported evidence changed or is incomplete: {relative}")


def _command(argv: list[str], log: Path | None = None, *, timeout: int = 60) -> str:
    result = subprocess.run(argv, cwd=REPOSITORY, capture_output=True, text=True, timeout=timeout, check=False)
    stdout, stderr = _redact(result.stdout), _redact(result.stderr)
    if log:
        log.write_text(stdout + stderr)
    if result.returncode:
        raise ValueError(f"Command failed ({result.returncode}): {argv!r}\n{stderr[-2000:]}")
    return stdout


def _redact(text: str) -> str:
    secret = os.environ.get("ANTHROPIC_API_KEY")
    return text.replace(secret, "[REDACTED]") if secret else text


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run_probe(arguments.manifest.resolve(), arguments.output)
