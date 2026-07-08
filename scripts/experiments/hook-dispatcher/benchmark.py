#!/usr/bin/env python3
"""Benchmark candidate Forge hook-dispatcher shapes.

This is a throwaway Phase 0 harness for docs/board/doing/forge_hook_dispatcher.
It measures cold process wall-time for the no-op path against a populated
project registry and a realistic cwd depth.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_REGISTRY_VERSION = 1


SHIM_SOURCE = r"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_REGISTRY_VERSION = 1


def _forge_home() -> Path:
    value = os.environ.get("FORGE_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".forge"


def _canonicalize(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _same_existing_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return False


def _paths_match(enrolled_path: str | Path, candidate_path: str | Path) -> bool:
    enrolled_key = _canonicalize(enrolled_path)
    candidate_key = _canonicalize(candidate_path)
    return enrolled_key == candidate_key or _same_existing_path(enrolled_key, candidate_key)


def _find_forge_root(start: Path) -> Path | None:
    current = start.expanduser().resolve(strict=False)
    while current != current.parent:
        if (current / ".forge").is_dir():
            return current
        if (current / ".git").exists():
            return None
        current = current.parent
    return None


def _read_registry() -> list[str]:
    path = _forge_home() / "projects.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != PROJECT_REGISTRY_VERSION:
            return []
        projects = data.get("projects", [])
        if not isinstance(projects, list):
            return []
        roots: list[str] = []
        for item in projects:
            if not isinstance(item, dict):
                return []
            canonical_path = item.get("canonical_path")
            if not isinstance(canonical_path, str) or not canonical_path:
                return []
            roots.append(_canonicalize(canonical_path))
        return roots
    except (OSError, json.JSONDecodeError):
        return []


def _is_enrolled(start: Path) -> bool:
    root = _find_forge_root(start)
    if root is None:
        return False
    return any(_paths_match(enrolled, root) for enrolled in _read_registry())


def main() -> int:
    if os.environ.get("FORGE_SESSION"):
        return 0
    if not _is_enrolled(Path.cwd()):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""


FULL_FORGE_GATE_SOURCE = """
from pathlib import Path

from forge.cli.main import main as _main
from forge.install.project_registry import ProjectRegistryStore

ProjectRegistryStore().lookup_enrolled_root(Path.cwd())
"""


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _run_once(command: list[str], env: dict[str, str], cwd: Path) -> float:
    start = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        raise RuntimeError(f"{command!r} exited {result.returncode}")
    return elapsed


def _measure(command: list[str], env: dict[str, str], cwd: Path, runs: int) -> dict[str, float]:
    timings = [_run_once(command, env, cwd) for _ in range(runs)]
    return {
        "p50_ms": _percentile(timings, 0.50),
        "p95_ms": _percentile(timings, 0.95),
        "min_ms": min(timings),
        "max_ms": max(timings),
    }


def _write_registry(forge_home: Path, enrolled_roots: list[Path]) -> None:
    forge_home.mkdir(parents=True)
    registry = {
        "schema_version": PROJECT_REGISTRY_VERSION,
        "projects": [
            {
                "canonical_path": str(root.resolve(strict=False)),
                "enrolled_at": "2026-07-08T00:00:00Z",
                "enrollment_source": "manual",
            }
            for root in enrolled_roots
        ],
    }
    (forge_home / "projects.json").write_text(json.dumps(registry), encoding="utf-8")


def _fixture(tmp: Path, project_count: int, depth: int) -> tuple[Path, Path, Path]:
    home = tmp / "home"
    forge_home = home / ".forge"
    enrolled_roots: list[Path] = []
    for index in range(project_count):
        root = tmp / "enrolled" / f"project-{index:02d}"
        (root / ".forge").mkdir(parents=True)
        (root / ".git").mkdir()
        enrolled_roots.append(root)

    probe_root = tmp / "probe-unenrolled"
    (probe_root / ".forge").mkdir(parents=True)
    (probe_root / ".git").mkdir()
    cwd = probe_root
    for index in range(depth):
        cwd = cwd / f"level-{index}"
    cwd.mkdir(parents=True)

    _write_registry(forge_home, enrolled_roots)
    return home, forge_home, cwd


def _write_shim(tmp: Path) -> Path:
    shim = tmp / "forge-hook-shim.py"
    shim.write_text(SHIM_SOURCE, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return shim


def _clean_env(home: Path, forge_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_HOME"] = str(forge_home)
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("FORGE_SESSION", None)
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--project-count", type=int, default=40)
    parser.add_argument("--depth", type=int, default=5)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="forge-hook-dispatcher-bench-") as tmp_raw:
        tmp = Path(tmp_raw)
        home, forge_home, cwd = _fixture(tmp, project_count=args.project_count, depth=args.depth)
        shim = _write_shim(tmp)
        env = _clean_env(home, forge_home)
        python = Path(sys.executable)

        results = {
            "runs": args.runs,
            "project_count": args.project_count,
            "cwd_depth": args.depth,
            "python": str(python),
            "forge_import_available": shutil.which(str(python)) is not None,
            "shim": _measure([str(python), str(shim)], env=env, cwd=cwd, runs=args.runs),
            "full_forge_gate": _measure(
                [str(python), "-c", FULL_FORGE_GATE_SOURCE],
                env=env,
                cwd=cwd,
                runs=args.runs,
            ),
        }
        json.dump(results, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
