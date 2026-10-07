"""One review budget per hook, shared by every file and cascade stage."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import monotonic
from typing import Callable, Iterator, ParamSpec, TypeVar

HOOK_TIMEOUT_SECONDS = 60
COMPLETION_RESERVE_SECONDS = 5
MAX_REVIEW_SECONDS = 45
_deadline: ContextVar[float | None] = ContextVar("supervisor_deadline", default=None)
_P = ParamSpec("_P")
_T = TypeVar("_T")


def hook_review_budget(function: Callable[_P, _T]) -> Callable[_P, _T]:
    """Start before hook context loading; reset even when Click exits the command."""

    @wraps(function)
    def bounded(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        token = _deadline.set(monotonic() + HOOK_TIMEOUT_SECONDS - COMPLETION_RESERVE_SECONDS)
        try:
            return function(*args, **kwargs)
        finally:
            _deadline.reset(token)

    return bounded


def review_deadline(timeout_seconds: int) -> float:
    """Return a bounded call deadline without extending the surrounding hook."""
    validate_timeout(timeout_seconds)
    expires = monotonic() + timeout_seconds
    hook = _deadline.get()
    return min(expires, hook) if hook is not None else expires


@contextmanager
def review_scope(expires: float) -> Iterator[None]:
    """Keep setup, auth, and retries inside the same manual/frontier call limit."""
    parent = _deadline.get()
    token = _deadline.set(min(parent, expires) if parent is not None else expires)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_review_seconds(timeout_seconds: int) -> float:
    remaining = review_deadline(timeout_seconds) - monotonic()
    if remaining < 1:
        raise TimeoutError("Supervisor hook budget exhausted; remaining review work is unavailable.")
    return remaining


def validate_timeout(timeout_seconds: int) -> None:
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= MAX_REVIEW_SECONDS:
        raise ValueError(f"Supervisor timeout must be 1-{MAX_REVIEW_SECONDS}s within the 60s executor hook.")
    from forge.install.codex_hooks import get_builtin_codex_entries
    from forge.install.preset import get_builtin_preset

    limits = [entry.timeout for entry in get_builtin_codex_entries() if entry.event == "PreToolUse"]
    limits.extend(
        hook.get("timeout", 0)
        for row in get_builtin_preset()["hooks"]["PreToolUse"]
        if row.get("matcher") in {"Write", "Edit"}
        for hook in row["hooks"]
    )
    if len(limits) != 3 or any(limit != HOOK_TIMEOUT_SECONDS for limit in limits):
        raise ValueError(
            "Supervisor deadline is unverified for this hook registration; restore the supported 60s hooks."
        )
