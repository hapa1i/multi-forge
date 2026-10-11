"""Dedicated native reviewer credentials and lease-owned copied inputs.

Ordinary Codex login files are never read or copied here. Authentication status
is local readiness, not proof of account billing settings or successful inference.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from forge.core.paths import get_forge_home
from forge.core.runtime.codex_review_source import (
    NativeSelection,
    directory_fd,
    read_regular,
)

MARKER = ".forge-codex-reviewer.json"
INPUT_MARKER = ".forge-review-inputs"
_BINARY_SHA256 = "74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0"
_binary_cache: dict[tuple[Any, ...], str] = {}


@dataclass(frozen=True)
class ReviewerHome:
    home: Path
    lease_fd: int
    binary: str
    env: dict[str, str] = field(repr=False)
    sqlite_home: Path


def reviewer_home() -> Path:
    return get_forge_home().absolute() / "reviewers" / "codex"


def reviewer_environment(home: Path) -> dict[str, str]:
    """Allow only process essentials; neither auth routing nor executor identity survives."""
    env = {
        key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TERM"}
    }
    env.update(CODEX_HOME=str(home), FORGE_DEPTH="2", PYTHON_DOTENV_DISABLED="1")
    return env


def require_codex_fork_binary() -> str:
    """Feature-specific admission without changing the general Codex runtime pin."""
    if sys.platform != "darwin":
        raise ValueError("Native Codex supervision is currently verified only on macOS")
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Install the supported Codex reviewer executable")
    path = Path(executable).resolve(strict=True)
    facts = path.stat()
    identity = (str(path), facts.st_dev, facts.st_ino, facts.st_size, facts.st_mtime_ns, facts.st_ctime_ns)
    digest = _binary_cache.get(identity)
    if digest is None:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        _binary_cache.clear()
        _binary_cache[identity] = digest
    if digest != _BINARY_SHA256:
        raise ValueError(
            "Native Codex supervision requires the verified macOS Codex 0.162.1 executable; this binary is untested"
        )
    return str(path)


def initialize_home(*, extra_usage_off: bool) -> Path:
    """Create an explicitly owned private home; never claim an existing unmarked store."""
    if not extra_usage_off:
        raise ValueError("Confirm that extra usage is off with --confirm-extra-usage-off before reviewer login")
    home = reviewer_home()
    home.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with directory_fd(home.parent) as parent:
        created = False
        try:
            os.mkdir(home.name, mode=0o700, dir_fd=parent)
            created = True
        except FileExistsError:
            pass
        with directory_fd(home) as owned:
            if created:
                descriptor = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=owned)
                with os.fdopen(descriptor, "w") as stream:
                    json.dump({"version": 1, "extra_usage_off_asserted": True}, stream)
                descriptor = os.open(
                    "review.lock", os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=owned
                )
                os.close(descriptor)
    _ownership(home)
    return home


def _ownership(home: Path) -> dict[str, Any]:
    with directory_fd(home) as descriptor:
        facts = os.fstat(descriptor)
        if facts.st_uid != os.getuid() or stat.S_IMODE(facts.st_mode) != 0o700:
            raise ValueError("Reviewer home must be owned by this user with mode 0700")
    data = json.loads(read_regular(home / MARKER, limit=4096))
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "extra_usage_off_asserted"}
        or data.get("version") != 1
        or type(data.get("extra_usage_off_asserted")) is not bool
    ):
        raise ValueError("Unmarked or unsupported reviewer home; use a new dedicated reviewer login")
    return data


@contextmanager
def reviewer_lease(home: Path) -> Iterator[int]:
    """Do not unlock explicitly: inherited descriptors retain the lock after owner death."""
    _ownership(home)
    with directory_fd(home) as directory:
        descriptor = os.open("review.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        facts = os.fstat(descriptor)
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_uid != os.getuid():
            raise ValueError("Invalid reviewer lease file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("A native review or login owns the reviewer home; retry after it completes") from exc
        yield descriptor
    finally:
        os.close(descriptor)


def _account(home: Path) -> str:
    if not _ownership(home)["extra_usage_off_asserted"]:
        raise ValueError("Dedicated reviewer login requires your extra-usage-off assertion")
    data = json.loads(read_regular(home / "auth.json", limit=100_000))
    if not isinstance(data, dict):
        raise ValueError("Malformed dedicated reviewer login")
    tokens = data.get("tokens")
    if data.get("auth_mode") != "chatgpt" or data.get("OPENAI_API_KEY") or not isinstance(tokens, dict):
        raise ValueError("Dedicated reviewer home requires an independent ChatGPT login")
    account = tokens.get("account_id")
    if not isinstance(account, str) or not account or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ValueError("Dedicated reviewer login is incomplete")
    return account


def auth_status() -> dict[str, Any]:
    """Return secret-free local readiness, with no login mutation or inference."""
    result: dict[str, Any] = dict(
        runtime="codex",
        home=str(reviewer_home()),
        ready=False,
        owned=False,
        auth_mode="subscription-only",
        extra_usage_off_asserted=False,
        lease_available=False,
        binary=None,
        unavailable_reason=None,
    )
    try:
        result["binary"] = require_codex_fork_binary()
        marker = _ownership(reviewer_home())
        result.update(owned=True, extra_usage_off_asserted=marker["extra_usage_off_asserted"])
        with reviewer_lease(reviewer_home()):
            result["lease_available"] = True
            _account(reviewer_home())
        result["ready"] = True
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["unavailable_reason"] = (
            str(exc)
            if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
            else "Dedicated reviewer login is unavailable; run forge policy supervisor auth login --runtime codex --confirm-extra-usage-off"
        )
    return result


def auth_login(*, extra_usage_off: bool) -> int:
    binary = require_codex_fork_binary()
    home = initialize_home(extra_usage_off=extra_usage_off)
    with reviewer_lease(home):
        result = subprocess.run(
            [
                binary,
                "login",
                "--device-auth",
                "-c",
                'forced_login_method="chatgpt"',
                "-c",
                'cli_auth_credentials_store="file"',
            ],
            env=reviewer_environment(home),
            cwd=str(home),
            check=False,
        )
        if result.returncode == 0:
            _account(home)
        return result.returncode


def auth_logout() -> None:
    home = reviewer_home()
    with reviewer_lease(home):
        binary = require_codex_fork_binary()
        result = subprocess.run(
            [binary, "logout", "-c", 'cli_auth_credentials_store="file"'],
            env=reviewer_environment(home),
            cwd=str(home),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise ValueError("Native reviewer logout failed; inspect the dedicated reviewer home")
        _clean_inputs(home)


def require_reviewer_auth(auth_mode: str) -> None:
    """Recheck current auth; ordinary runtime preflight caches cannot authorize this route."""
    require_codex_fork_binary()
    if auth_mode == "subscription-only":
        home = reviewer_home()
        try:
            with reviewer_lease(home):
                _account(home)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Run forge policy supervisor auth login --runtime codex --confirm-extra-usage-off"
            ) from exc
    elif auth_mode == "api":
        from forge.core.runtime.codex_preflight import codex_api_key_for_subprocess

        if not codex_api_key_for_subprocess():
            raise ValueError("Native API review requires CODEX_API_KEY in the environment or Forge credentials.yaml")
    else:
        raise ValueError("Native supervision requires subscription-only or api auth")


def require_source_account(selection: NativeSelection) -> None:
    """Compare locally without persisting or displaying account identifiers."""
    home = reviewer_home()
    with reviewer_lease(home):
        account = _account(home)
        if any(prefix.metadata["creator_account_id"] != account for prefix in selection.prefixes):
            raise ValueError("Reviewer login does not match the recorded source account")


@contextmanager
def prepare_reviewer_home(selection: NativeSelection, *, auth_mode: str) -> Iterator[ReviewerHome]:
    """Stage only immutable selected ancestry, plus a fresh per-attempt native index."""
    binary = require_codex_fork_binary()
    temporary = None
    if auth_mode == "api":
        from forge.core.runtime.codex_preflight import codex_api_key_for_subprocess

        key = codex_api_key_for_subprocess()
        if not key:
            raise ValueError("Native API review requires an explicit CODEX_API_KEY")
        parent = reviewer_home().parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _clean_abandoned_api_homes(parent)
        with directory_fd(parent):
            temporary = Path(tempfile.mkdtemp(prefix="codex-api-", dir=parent))
        home = temporary
        (home / MARKER).write_text(json.dumps({"version": 1, "extra_usage_off_asserted": False}))
        (home / "review.lock").touch(mode=0o600)
    elif auth_mode == "subscription-only":
        key = None
        home = reviewer_home()
    else:
        raise ValueError("Unsupported native reviewer auth route")
    try:
        with reviewer_lease(home) as lease:
            if auth_mode == "subscription-only":
                account = _account(home)
                if any(prefix.metadata["creator_account_id"] != account for prefix in selection.prefixes):
                    raise ValueError("Reviewer login does not match the recorded source account")
            _clean_inputs(home)
            for name in ("sessions", "review-index"):
                path = home / name
                with directory_fd(home) as parent_fd:
                    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                with directory_fd(path) as child_fd:
                    descriptor = os.open(
                        INPUT_MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=child_fd
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(b"1\n")
            for prefix in selection.prefixes:
                # Native discovery requires this dated layout, not arbitrary filenames.
                relative = Path(*prefix.path.parts[-4:])
                destination = home / "sessions" / relative
                current = home / "sessions"
                for part in relative.parts[:-1]:
                    with directory_fd(current) as parent_fd:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                        except FileExistsError:
                            pass
                    current /= part
                with directory_fd(destination.parent) as parent_fd:
                    descriptor = os.open(
                        destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd
                    )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(prefix.data)
                if hashlib.sha256(read_regular(destination, limit=len(prefix.data))).hexdigest() != prefix.digest:
                    raise ValueError("Native input copy failed hash verification")
            env = reviewer_environment(home)
            if key:
                env["CODEX_API_KEY"] = key
            yield ReviewerHome(home, lease, binary, env, home / "review-index")
            # The invoker returns only after watchdog cleanup. No explicit unlock
            # or removal happens on hook death; the next lease holder recovers it.
    finally:
        if temporary is not None:
            # A crashed watcher can return before the independent anchor expires.
            # Reacquire on a new description before removing even ephemeral input.
            try:
                with reviewer_lease(temporary):
                    with directory_fd(temporary.parent) as parent_fd:
                        shutil.rmtree(temporary.name, dir_fd=parent_fd)
            except (OSError, ValueError):
                pass  # Still owned by an anchor; leave marked recovery evidence.


def verify_selected_inputs(home: Path, selection: NativeSelection) -> bool:
    """Confirm that the native runtime did not append to or alter the selected copies."""
    for prefix in selection.prefixes:
        path = home / "sessions" / Path(*prefix.path.parts[-4:])
        if hashlib.sha256(read_regular(path, limit=len(prefix.data))).hexdigest() != prefix.digest:
            return False
    return True


def _clean_inputs(home: Path) -> None:
    with directory_fd(home) as descriptor:
        for name in ("sessions", "review-index"):
            path = home / name
            if not path.exists() and not path.is_symlink():
                continue
            if read_regular(path / INPUT_MARKER, limit=16) != b"1\n":
                raise ValueError("Refusing unmarked reviewer inputs")
            shutil.rmtree(name, dir_fd=descriptor)


def _clean_abandoned_api_homes(parent: Path) -> None:
    """Recover marked ephemeral inputs only after every inherited lease has closed."""
    with directory_fd(parent) as descriptor:
        for name in os.listdir(descriptor):
            if not name.startswith("codex-api-"):
                continue
            home = parent / name
            try:
                if _ownership(home)["extra_usage_off_asserted"]:
                    continue
                with reviewer_lease(home):
                    shutil.rmtree(name, dir_fd=descriptor)
            except (OSError, ValueError):
                continue  # Active, unmarked or unsafe stores remain untouched.
