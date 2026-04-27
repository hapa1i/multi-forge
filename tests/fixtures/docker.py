"""Shared Docker fixtures for in-container testing.

These fixtures manage Docker containers for testing code that touches home-directory
paths (~/.forge/, ~/.claude/, .claude/). The container provides isolation by default —
even if test code forgets to use fixture paths, it can't corrupt host data.

Two execution modes:
1. Docker mode: Host pytest spawns containers and execs commands into them (local dev)
2. Local mode: Runs directly when already inside test container (CI/docker-compose)

Usage:
    # In conftest.py
    from tests.fixtures.docker import synced_container, clean_workspace

    # In test file
    def test_something(clean_workspace):
        result = clean_workspace.exec("forge session start test")
        assert result.returncode == 0
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Protocol

import pytest
from _pytest.nodes import Item

# Module-level state for log capture hook
_active_container_id: str | None = None


def _detect_claude_code_version() -> str:
    """Detect installed Claude Code version via `claude --version`."""
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            # Output is like "2.1.76 (Claude Code)" — take first token
            return result.stdout.strip().split()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "latest"


CLAUDE_CODE_VERSION = _detect_claude_code_version()


class ContainerLike(Protocol):
    """Protocol for container-like objects that can execute commands.

    Provides helper methods for file operations without shell quote escaping.
    Used by integration test fixtures (clean_workspace, mock_claude_workspace).

    Usage:
        def test_something(clean_workspace: ContainerLike):
            # File operations (no escaping needed!)
            clean_workspace.write_file("$HOME/.forge/config.yaml", "key: value")
            clean_workspace.write_json("$HOME/.forge/data.json", {"version": 1})

            # Run commands
            result = clean_workspace.exec("forge session start test")
            assert result.returncode == 0

            # Verify output
            data = clean_workspace.read_json("$HOME/.forge/output.json")
            assert data["status"] == "success"
    """

    def exec(self, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Execute a command and return the result."""
        ...

    def write_file(self, path: str, content: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write content to file using heredoc (no quote escaping needed)."""
        ...

    def write_json(self, path: str, data: dict, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write JSON data to file (handles serialization + escaping)."""
        ...

    def mkdir(self, path: str, parents: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Create directory (optionally with parents)."""
        ...

    def read_file(self, path: str, timeout: int = 30) -> str:
        """Read file contents (raises on error)."""
        ...

    def read_json(self, path: str, timeout: int = 30) -> dict:
        """Read and parse JSON file."""
        ...

    def file_exists(self, path: str, timeout: int = 30) -> bool:
        """Check if file exists."""
        ...


@dataclass
class DockerContainer:
    """Represents a running Docker container for tests."""

    container_id: str
    image: str

    def exec(self, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Execute a command inside the container."""
        return subprocess.run(
            ["docker", "exec", self.container_id, "bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def write_file(self, path: str, content: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write content to file using heredoc (no quote escaping needed).

        Note: Heredoc adds a trailing newline, so we strip it with head -c -1.
        Special case: empty content writes empty file (not a newline).
        """
        if not content:
            # Empty content - just truncate the file
            return self.exec(f'> "{path}"', timeout=timeout)

        cmd = f"""cat > "{path}" << 'FORGE_EOF'
{content}
FORGE_EOF
head -c -1 "{path}" > "{path}.tmp" && mv "{path}.tmp" "{path}"
"""
        return self.exec(cmd, timeout=timeout)

    def write_json(self, path: str, data: dict, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write JSON data to file (handles serialization + escaping)."""
        import json

        content = json.dumps(data, indent=2)
        return self.write_file(path, content, timeout=timeout)

    def mkdir(self, path: str, parents: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Create directory (optionally with parents)."""
        flag = "-p" if parents else ""
        return self.exec(f'mkdir {flag} "{path}"', timeout=timeout)

    def read_file(self, path: str, timeout: int = 30) -> str:
        """Read file contents (raises on error)."""
        result = self.exec(f'cat "{path}"', timeout=timeout)
        if result.returncode != 0:
            raise FileNotFoundError(f"Failed to read {path}: {result.stderr}")
        return result.stdout

    def read_json(self, path: str, timeout: int = 30) -> dict:
        """Read and parse JSON file."""
        import json

        content = self.read_file(path, timeout=timeout)
        return json.loads(content)

    def file_exists(self, path: str, timeout: int = 30) -> bool:
        """Check if file exists."""
        result = self.exec(f'test -f "{path}"', timeout=timeout)
        return result.returncode == 0


@dataclass
class LocalExecution:
    """Executes commands directly on the local system (for running inside container)."""

    def exec(self, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Execute a command locally."""
        return subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def write_file(self, path: str, content: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write content to file using heredoc (no quote escaping needed).

        Note: Heredoc adds a trailing newline, so we strip it with head -c -1.
        Special case: empty content writes empty file (not a newline).
        """
        if not content:
            # Empty content - just truncate the file
            return self.exec(f'> "{path}"', timeout=timeout)

        cmd = f"""cat > "{path}" << 'FORGE_EOF'
{content}
FORGE_EOF
head -c -1 "{path}" > "{path}.tmp" && mv "{path}.tmp" "{path}"
"""
        return self.exec(cmd, timeout=timeout)

    def write_json(self, path: str, data: dict, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Write JSON data to file (handles serialization + escaping)."""
        import json

        content = json.dumps(data, indent=2)
        return self.write_file(path, content, timeout=timeout)

    def mkdir(self, path: str, parents: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Create directory (optionally with parents)."""
        flag = "-p" if parents else ""
        return self.exec(f'mkdir {flag} "{path}"', timeout=timeout)

    def read_file(self, path: str, timeout: int = 30) -> str:
        """Read file contents (raises on error)."""
        result = self.exec(f'cat "{path}"', timeout=timeout)
        if result.returncode != 0:
            raise FileNotFoundError(f"Failed to read {path}: {result.stderr}")
        return result.stdout

    def read_json(self, path: str, timeout: int = 30) -> dict:
        """Read and parse JSON file."""
        import json

        content = self.read_file(path, timeout=timeout)
        return json.loads(content)

    def file_exists(self, path: str, timeout: int = 30) -> bool:
        """Check if file exists."""
        result = self.exec(f'test -f "{path}"', timeout=timeout)
        return result.returncode == 0


def _docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _claude_code_available_locally() -> bool:
    """Check if we're already inside a Forge test container with Claude Code.

    We intentionally key this off the test image layout (`/forge`) plus known
    Claude install locations so a host-machine Claude install doesn't suppress
    Docker-backed integration runs.
    """
    if not Path("/forge").exists():
        return False

    known_paths = [
        Path("/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js"),
        Path("/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
        Path("/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude"),
        Path("/root/.local/bin/claude"),
    ]
    return any(path.exists() for path in known_paths)


def _image_exists(image: str) -> bool:
    """Check if a Docker image exists locally."""
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    return result.returncode == 0


def _get_image_revision(image: str) -> str | None:
    """Return the Forge source revision label baked into a Docker image."""
    result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "-f",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
            image,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    revision = result.stdout.strip()
    return revision or None


def _find_repo_root() -> Path:
    """Find repository root by searching for pyproject.toml.

    More robust than hardcoded parent traversal — works even if test
    file location changes.
    """
    p = Path(__file__).resolve()
    while p.parent != p:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    raise RuntimeError("Could not find repo root (no pyproject.toml found)")


def _get_forge_revision(repo_root: Path) -> str:
    """Return a revision token for the current Forge source tree.

    Clean trees use the current ``HEAD`` SHA. Dirty trees include a short hash
    of the actual worktree diff plus untracked file contents, so local Docker
    images rebuild when uncommitted source changes.
    """
    try:
        rev_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if rev_result.returncode != 0:
            return "unknown"

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if status_result.returncode != 0:
            return rev_result.stdout.strip()

        revision = rev_result.stdout.strip()
        if status_result.stdout.strip():
            dirty_fingerprint = _get_dirty_worktree_fingerprint(repo_root)
            if dirty_fingerprint is None:
                return f"{revision}-dirty"
            return f"{revision}-dirty-{dirty_fingerprint}"
        return revision
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def _get_dirty_worktree_fingerprint(repo_root: Path) -> str | None:
    """Hash tracked diffs plus untracked file contents for Docker cache busting."""
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"],
            cwd=repo_root,
            capture_output=True,
            timeout=30,
        )
        if diff_result.returncode != 0:
            return None

        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo_root,
            capture_output=True,
            timeout=30,
        )
        if untracked_result.returncode != 0:
            return None

        digest = hashlib.sha256()
        digest.update(diff_result.stdout)

        for raw_path in filter(None, untracked_result.stdout.split(b"\x00")):
            digest.update(b"\x00PATH\x00")
            digest.update(raw_path)

            file_path = repo_root / raw_path.decode("utf-8", errors="surrogateescape")
            if not file_path.is_file():
                continue

            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    digest.update(chunk)

        return digest.hexdigest()[:12]
    except (OSError, subprocess.TimeoutExpired):
        return None


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Session-scoped fixture to check Docker availability once."""
    return _docker_available()


@pytest.fixture(scope="session")
def local_claude_available() -> bool:
    """Session-scoped fixture to check if running inside test container."""
    return _claude_code_available_locally()


@pytest.fixture(scope="session")
def forge_test_image(docker_available: bool, local_claude_available: bool) -> str | None:
    """Build or use existing forge-claude-test image.

    Returns None if running in local mode (inside container).

    The image tag includes the Claude Code version to ensure cache invalidation
    when the version changes. Version is detected from `claude --version`.
    """
    # If we're already inside a container with Claude Code, no image needed
    if local_claude_available:
        return None

    if not docker_available:
        pytest.fail(
            "Docker not available and not running inside test container. Install Docker or run inside container."
        )

    repo_root = _find_repo_root()
    forge_revision = _get_forge_revision(repo_root)

    # Include version in tag for cache invalidation when Claude version changes
    image_name = f"forge-claude-test:{CLAUDE_CODE_VERSION}"

    needs_build = not _image_exists(image_name)
    if not needs_build:
        image_revision = _get_image_revision(image_name)
        if image_revision != forge_revision:
            if image_revision is None:
                print(f"\nDocker image {image_name} is missing a Forge revision label. Rebuilding...")
            else:
                print(
                    f"\nDocker image {image_name} is stale "
                    f"(image_rev={image_revision}, repo_rev={forge_revision}). Rebuilding..."
                )
            needs_build = True

    if not needs_build:
        return image_name

    # Build the image
    dockerfile = repo_root / "docker" / "Dockerfile.forge"

    if not dockerfile.exists():
        pytest.fail(f"Dockerfile not found at {dockerfile}. Run from repo root or check docker/ directory.")

    print(f"\nBuilding Docker image {image_name} (Claude Code {CLAUDE_CODE_VERSION})...")
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(dockerfile),
            "--build-arg",
            f"CLAUDE_VERSION={CLAUDE_CODE_VERSION}",
            "--build-arg",
            f"FORGE_REV={forge_revision}",
            "-t",
            image_name,
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        timeout=600,  # 10 minute timeout for build
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to build Docker image:\n{result.stderr}")

    return image_name


@pytest.fixture(scope="session")
def synced_container(
    forge_test_image: str | None,
    local_claude_available: bool,
) -> Generator[ContainerLike, None, None]:
    """Session-scoped container with dependencies pre-installed.

    This fixture creates ONE container for the entire test session. Dependencies
    are already baked into the Docker image (see Dockerfile line 62). Individual
    tests reuse this container for fast execution.

    Two modes:
    - Local mode: If Claude Code is available locally (running inside container),
      returns LocalExecution that runs commands directly.
    - Docker mode: Spawns a single persistent container from the test image.
    """
    global _active_container_id

    # Local mode: already inside test container (deps installed at image build)
    if local_claude_available:
        yield LocalExecution()
        return

    # Docker mode: spawn container
    if forge_test_image is None:
        pytest.fail("No test image available and not running locally. Run 'make test-integration' to build images.")

    # Build docker run command with platform-specific options
    cmd = [
        "docker",
        "run",
        "-d",  # detached
        "--rm",  # remove on stop
        "-w",
        "/forge",
    ]

    # UID/GID mapping for Linux CI runners
    # On macOS Docker Desktop, this can cause surprising ownership issues,
    # so we only apply it on Linux.
    if platform.system() == "Linux":
        # Note: if os.getuid() == 0 (already root), this is a no-op
        cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    cmd.extend(
        [
            forge_test_image,
            "tail",
            "-f",
            "/dev/null",  # Keep container running
        ]
    )

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to start container: {result.stderr}")

    container_id = result.stdout.strip()
    _active_container_id = container_id  # Store for log capture hook
    container = DockerContainer(container_id=container_id, image=forge_test_image)

    # Brief wait for container init
    time.sleep(0.5)

    # Quick verification that Forge can import (validates image build)
    # Dependencies are already baked into the Docker image (see Dockerfile line 62)
    verify_result = container.exec("uv run python -c 'import forge.cli.main'", timeout=10)
    if verify_result.returncode != 0:
        subprocess.run(["docker", "stop", container_id], capture_output=True, timeout=30)
        _active_container_id = None
        pytest.fail(f"Forge import failed: {verify_result.stderr}")

    try:
        yield container
    finally:
        # Cleanup: stop container (--rm flag handles removal)
        subprocess.run(
            ["docker", "stop", container_id],
            capture_output=True,
            timeout=30,
        )
        _active_container_id = None


@pytest.fixture(scope="session")
def base_git_repo(synced_container: ContainerLike) -> ContainerLike:
    """Session-scoped git repo initialized at /workspace.

    Created ONCE per test session. Tests should use clean_workspace
    fixture to reset between tests.

    Note: Uses `git init -b main` to ensure consistent branch naming
    across different git versions (some default to 'master').
    """
    result = synced_container.exec("""
        mkdir -p /workspace && cd /workspace
        git init -b main
        git config user.email "test@forge.local"
        git config user.name "Forge Test"
        echo "# Test Workspace" > README.md
        git add . && git commit -m "init"
    """)
    if result.returncode != 0:
        pytest.fail(f"Failed to initialize git repo: {result.stderr}")
    return synced_container


@pytest.fixture
def clean_workspace(base_git_repo: ContainerLike) -> ContainerLike:
    """Per-test: reset workspace to clean state.

    This is FAST (~10-50ms) compared to recreating containers (~2s).
    Resets:
    - Git history (hard reset to initial commit)
    - Working directory (git clean)
    - Tracked file changes (git checkout)
    - Config directories (.claude, .forge)
    - Git worktrees (except /workspace)
    - Git branches (except main)
    """
    # Hard reset to initial commit (undo any commits made by tests)
    # This ensures tests that commit files don't pollute subsequent tests
    base_git_repo.exec("""
        cd /workspace
        INIT_COMMIT=$(git rev-list --max-parents=0 HEAD)
        git checkout main 2>/dev/null || true
        git reset --hard $INIT_COMMIT
        """)

    # Reset working directory and remove config dirs
    result = base_git_repo.exec("cd /workspace && git clean -fdx && git checkout -- . && rm -rf .claude .forge")
    if result.returncode != 0:
        pytest.fail(f"Failed to reset workspace: {result.stderr}")

    # Remove any worktrees created by previous tests (sibling dirs like /workspace-*)
    # git worktree list shows: /workspace  abc1234 [main]
    # We want to remove all worktrees except /workspace
    base_git_repo.exec("""
        cd /workspace
        for wt in $(git worktree list --porcelain | grep '^worktree ' | cut -d' ' -f2 | grep -v '^/workspace$'); do
            git worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
        done
        """)

    # Also remove any /workspace-* sibling directories that might have been created
    # manually (not as proper git worktrees). This catches orphaned directories.
    base_git_repo.exec("""
        rm -rf /workspace-* 2>/dev/null || true
        """)

    # Delete any branches except main (cleanup from fork/worktree tests)
    base_git_repo.exec("""
        cd /workspace
        for branch in $(git branch --format='%(refname:short)' | grep -v '^main$'); do
            git branch -D "$branch" 2>/dev/null || true
        done
        """)

    return base_git_repo


# -----------------------------------------------------------------------------
# Log capture on failure (pytest hook)
# -----------------------------------------------------------------------------


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: Item, call: pytest.CallInfo) -> Generator:
    """Capture Docker container logs and state on test failure.

    Guard conditions:
    - Only on failure (not skipped, not passed)
    - Only for Docker containers (not LocalExecution mode)
    - Only when a container is active
    """
    outcome = yield
    if outcome is None:
        return
    report = outcome.get_result()

    # Only capture on actual failures in the call phase
    if report.when != "call" or report.outcome != "failed":
        return

    # Only capture if we have an active Docker container
    if _active_container_id is None:
        return

    # Capture container state and logs
    try:
        # Container state (brief inspect output)
        inspect_result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} - {{.State.StartedAt}}",
                _active_container_id,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Last 100 lines of logs
        logs_result = subprocess.run(
            ["docker", "logs", "--tail", "100", _active_container_id],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Append to report
        extra_info = [
            "",
            "=" * 60,
            "Docker Container Debug Info",
            "=" * 60,
            f"Container ID: {_active_container_id}",
            f"State: {inspect_result.stdout.strip() if inspect_result.returncode == 0 else 'unknown'}",
            "",
            "Last 100 log lines:",
            "-" * 40,
            logs_result.stdout if logs_result.returncode == 0 else "(no logs captured)",
            logs_result.stderr if logs_result.stderr else "",
            "=" * 60,
        ]

        # Append to longrepr for display
        if report.longrepr is not None:
            if hasattr(report.longrepr, "addsection"):
                report.longrepr.addsection("Docker Debug", "\n".join(extra_info))
            else:
                # For string longrepr, append directly
                report.longrepr = str(report.longrepr) + "\n".join(extra_info)

    except Exception as e:
        # Don't let log capture failure break test reporting
        print(f"Warning: Failed to capture Docker logs: {e}", file=sys.stderr)
