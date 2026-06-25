"""Regression: a failed *read* (OSError) must not be treated as corruption, so
``forge clean`` never deletes durable state it merely failed to open.

Bug: every durable-state reader wrapped ``OSError`` from ``open()`` in a
``*CorruptedError`` (a ``StateCorruptedError``). ``_detect_corrupt_state`` flags
``StateCorruptedError`` for removal, so a transient I/O error, a momentarily locked
file, or a permissions glitch would make ``forge clean`` DELETE a registry, index,
manifest, or installed-manifest -- failing OPEN toward destruction of state whose
contents were never shown to be bad.

Root cause: the ``except OSError`` arms in the readers (``session/store.py``,
``session/index.py``, ``install/tracking.py``, ``proxy/proxies.py``,
``backend/registry.py``) raised the corruption variant.

Fix: a parallel ``StateUnreadableError`` family. Readers raise the ``*UnreadableError``
variant on ``OSError``; ``_detect_corrupt_state`` only treats ``StateCorruptedError`` as
deletable, and the CLI routes ``StateUnreadableError`` to a check/retry handler that
never deletes. The domain variants stay ``ForgeSessionError`` / ``ForgeInstallError`` so
existing fail-open degrade sites (session picker/list) still catch them.
"""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import _detect_corrupt_state, run_clean
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError

pytestmark = pytest.mark.regression


def _fail_open_for(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make ``open(target, ...)`` raise OSError; delegate every other open.

    Path-scoped so only the file under test fails -- all other reads during a
    ``forge clean`` (index, tracking, manifests) proceed normally.
    """
    real_open = builtins.open
    target_str = str(target)

    def fake_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(file) == target_str:
            raise OSError("simulated transient I/O failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_clean_does_not_flag_or_delete_unreadable_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The HIGH-severity fix: an unreadable global registry is neither flagged nor deleted."""
    from forge.proxy.proxies import get_proxy_registry_path

    fr = tmp_path / "project"
    fr.mkdir()
    reg = get_proxy_registry_path()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"version": 1, "proxies": {}}), encoding="utf-8")

    _fail_open_for(monkeypatch, reg)

    # Direct: the deletion-candidate detector must skip a read that failed (OSError),
    # because the contents are unknown, not known-bad.
    corrupt = _detect_corrupt_state({fr})
    assert str(reg) not in corrupt.items
    assert corrupt.count == 0

    # End-to-end: run_clean must leave the file on disk.
    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path, forge_root=fr)
    run_clean(ctx=ctx, scope="all")
    assert reg.exists()


def test_corrupt_registry_is_still_flagged(tmp_path: Path) -> None:
    """Guards the narrowing: genuine bad *content* (not a read failure) is still deletable.

    Without this, a fix that silenced read failures could over-correct and stop flagging
    real corruption -- the opposite failure mode.
    """
    from forge.proxy.proxies import get_proxy_registry_path

    fr = tmp_path / "project"
    fr.mkdir()
    reg = get_proxy_registry_path()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("{not valid json", encoding="utf-8")

    corrupt = _detect_corrupt_state({fr})
    assert str(reg) in corrupt.items


@pytest.mark.parametrize("kind", ["proxy", "backend", "tracking", "index", "manifest"])
def test_reader_raises_unreadable_not_corrupted_on_oserror(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every durable-state reader maps a read OSError to StateUnreadableError, not corruption."""
    read: Callable[[], object]
    if kind == "proxy":
        from forge.proxy.proxies import ProxyRegistryStore, get_proxy_registry_path

        path = get_proxy_registry_path()
        read = lambda: ProxyRegistryStore().read()  # noqa: E731
    elif kind == "backend":
        from forge.backend.registry import (
            BackendRegistryStore,
            get_backend_registry_path,
        )

        path = get_backend_registry_path()
        read = lambda: BackendRegistryStore().read()  # noqa: E731
    elif kind == "tracking":
        from forge.install.tracking import TrackingStore, get_tracking_path

        path = get_tracking_path()
        read = lambda: TrackingStore().read()  # noqa: E731
    elif kind == "index":
        from forge.session.index import IndexStore, get_index_path

        path = get_index_path()
        read = lambda: IndexStore().read()  # noqa: E731
    else:  # manifest
        from forge.session.models import create_session_state
        from forge.session.store import SessionStore, get_manifest_path

        fr = tmp_path / "project"
        SessionStore(str(fr), "sess").write(create_session_state("sess", worktree_path=str(fr)))
        path = get_manifest_path(str(fr), "sess")
        read = lambda: SessionStore(str(fr), "sess").read()  # noqa: E731

    # Ensure the file exists (so the reader gets past its exists() guard to open()).
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    _fail_open_for(monkeypatch, path)

    with pytest.raises(StateUnreadableError) as ei:
        read()
    # The crux: an unreadable file is NOT corruption, so forge clean leaves it alone.
    assert not isinstance(ei.value, StateCorruptedError)


def test_domain_unreadable_variants_keep_their_domain_base() -> None:
    """Unreadable variants stay catchable by domain bases so fail-open degrade sites survive.

    Session picker/list code catches ``ForgeSessionError`` to skip a bad session rather
    than crash. If the unreadable variants dropped that base, one locked manifest would
    abort the whole listing.
    """
    from forge.install.exceptions import ForgeInstallError, TrackingUnreadableError
    from forge.session.exceptions import (
        ForgeSessionError,
        IndexUnreadableError,
        ManifestUnreadableError,
    )

    assert issubclass(ManifestUnreadableError, ForgeSessionError)
    assert issubclass(IndexUnreadableError, ForgeSessionError)
    assert issubclass(TrackingUnreadableError, ForgeInstallError)
    # ...but none of them are corruption.
    assert not issubclass(ManifestUnreadableError, StateCorruptedError)
    assert not issubclass(IndexUnreadableError, StateCorruptedError)
    assert not issubclass(TrackingUnreadableError, StateCorruptedError)


def test_handle_session_error_routes_unreadable_to_retry_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session command surfacing an unreadable manifest gets the check/retry message, not delete."""
    from forge.cli import output
    from forge.session.exceptions import ManifestUnreadableError

    calls: dict[str, object] = {}
    monkeypatch.setattr(output, "handle_unreadable_state_error", lambda e, **_kw: calls.setdefault("err", e))
    monkeypatch.setattr(
        output,
        "handle_corrupt_state_error",
        lambda e, **_kw: calls.setdefault("corrupt", e),  # must NOT fire
    )

    err = ManifestUnreadableError("/p/forge.session.json", "read error")
    output.handle_session_error(err)

    assert calls.get("err") is err
    assert "corrupt" not in calls
