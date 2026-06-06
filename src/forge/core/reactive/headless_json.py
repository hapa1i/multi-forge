"""Shared `claude -p --output-format json` capability + conversion helpers (Phase 5).

Centralizes everything BOTH headless runners (`run_claude_session` and
`ClaudeHeadlessInvoker`) need to request JSON output safely, so no caller
hand-appends the flag:

- **Spike verdicts as named constants** (metric-evidence Phase 5a; see
  `scripts/experiments/headless-cost-report/`). Tests monkeypatch these; the
  public functions read them live.
- A **capability guard** built on retry-once-and-latch: request JSON
  optimistically; if the CLI rejects the flag, retry once without it and latch
  "unsupported" for the process so siblings skip it. Strictly cheaper than a
  version probe (a modern CLI pays ZERO extra spawns; an old CLI self-heals with
  one instant flag-rejection) and it never shells out on the hot path.
- `usd_to_micros` -- the single ledger-facing USD->micros conversion (Decimal,
  not binary float), shared so the `claude -p` path and the proxy cost path agree.

Kept separate from `structured_output.py` so `parse_headless_envelope` imports
only `usd_to_micros` (no heavier deps) and the import direction stays acyclic.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# ---- Spike verdicts (metric-evidence Phase 5a, Claude Code 2.1.165) ---------
# Encoded as named constants, not prose, so the wiring reads them and tests
# monkeypatch them ("the spike confirmed it" never becomes tribal memory).

# Flag tokens that, if present in argv, suppress JSON output (a per-combo
# carve-out). The 5a matrix found NONE incompatible on 2.1.165 (plain, --bare,
# --resume --fork-session, --model, and the full supervisor combo all returned
# valid JSON with reported cost), so this is empty -- a hook for a future
# regression, not a current carve-out.
_JSON_INCOMPATIBLE: frozenset[str] = frozenset()

# `is_error` is a real top-level field on the result element and can be `true`
# with exit 0 (subtype error_during_execution / error_max_turns / ...), so a
# runtime-reported error must not read as success in the usage ledger.
_JSON_IS_ERROR_RELIABLE = True

# Runtime latch: flips True if a run proves the CLI rejects --output-format json
# (the retry-once backstop sets it so siblings skip the flag for this process).
_json_output_unsupported = False

# argparse-style rejection of an unknown/invalid flag (the retry trigger).
# Requires UNAMBIGUOUS rejection phrasing. A bare ``--output-format`` alternative
# was removed: it matched any non-zero exit whose stderr merely echoed the failing
# command line (e.g. a transient "API Error: 529 ... claude -p --output-format
# json"), misfiring the retry -- which latches the JSON capability off process-wide
# AND, on a proxied worker, re-runs the request for a duplicate proxy-side cost row.
# Real rejections still carry one of the phrases below ("unknown option" covers the
# regression fixture "error: unknown option '--output-format'").
_REJECTION_RE = re.compile(
    r"unknown option|unknown argument|unexpected argument|unrecognized|" r"invalid.{0,40}output-format|allowed choices",
    re.IGNORECASE,
)


def should_request_json(argv: Sequence[str]) -> bool:
    """True if it is safe to add ``--output-format json`` for this argv.

    Deliberately does NOT probe ``claude --version`` (which would spawn a
    subprocess on every cold process and on the parallel hot path, and would be
    consumed by ``subprocess.Popen`` mocks in tests). Safety comes from the
    retry-once-and-latch backstop instead: request optimistically unless this
    process has already proven the flag unsupported, or the combo is carved out.
    """
    if _json_output_unsupported:
        return False
    return not any(tok in _JSON_INCOMPATIBLE for tok in argv)


def prepare_json_argv(argv: list[str], output_format: str | None) -> tuple[list[str], bool]:
    """Return ``(argv_to_run, json_requested)``.

    Appends ``--output-format <fmt>`` when ``output_format`` is set AND the
    capability guard allows it. Callers pass the base argv (no ``--output-format``
    token); this is the single injection point shared by both runners.

    Only ``"json"`` is parseable end-to-end today: ``parse_headless_envelope`` reads a
    batch JSON envelope, not realtime ``stream-json`` (NDJSON). Do not pass
    ``"stream-json"`` until the parser is wired to consume it, or cost/usage drop.
    """
    if output_format and should_request_json(argv):
        return [*argv, "--output-format", output_format], True
    return list(argv), False


def is_json_flag_rejection(returncode: int, stderr: str | None) -> bool:
    """True if a nonzero exit looks like the CLI rejecting ``--output-format``.

    The retry-once trigger: a misdetection where the version gate allowed the flag
    but the CLI still refused it. A successful run (rc 0) is never a rejection.
    """
    return returncode != 0 and bool(_REJECTION_RE.search(stderr or ""))


def mark_json_output_unsupported() -> None:
    """Latch JSON output as unsupported for this process (after a flag rejection)."""
    global _json_output_unsupported  # noqa: PLW0603 — process-scoped capability latch
    _json_output_unsupported = True


def treat_is_error_as_failure() -> bool:
    """Whether a parsed ``is_error: true`` should map to a failed usage status."""
    return _JSON_IS_ERROR_RELIABLE


def usd_to_micros(usd: object) -> int | None:
    """Convert a reported USD figure to integer micro-USD, or None.

    Uses ``Decimal(str(usd))`` to avoid binary-float / banker's-rounding drift on
    ledger integers. Returns None for None / non-numeric / bool (a JSON ``true``
    must never read as cost 1).
    """
    if isinstance(usd, bool) or not isinstance(usd, (int, float)):
        return None
    try:
        return int(Decimal(str(usd)) * 1_000_000)
    except (InvalidOperation, ValueError):
        return None


def reset_json_capability_cache() -> None:
    """Reset the process latch (for tests)."""
    global _json_output_unsupported  # noqa: PLW0603
    _json_output_unsupported = False
