"""Regression: policy session-resolution failures must print to stderr, not stdout.

forge_cli_cleanup Slice 12 added ``forge policy shadow status --json``, a read leaf
under the stream contract (results/JSON on stdout, diagnostics on stderr). But the
shared ``_resolve_policy_session`` helper wrote its "session not found" / "multiple
sessions" diagnostics through the stdout module console, so a failing
``policy shadow status <bad> --json`` emitted the error on stdout with empty stderr --
polluting the results stream that machine consumers parse.

Root cause: stdout console used for diagnostics in ``_resolve_policy_session``.
Fix: route ``_resolve_policy_session`` diagnostics through stderr. JSON-capable shadow reads keep that stream boundary
while emitting a machine-readable error object.
Affected: ``src/forge/cli/policy.py`` (``_resolve_policy_session``).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def test_policy_resolver_error_goes_to_stderr_not_stdout() -> None:
    """`policy shadow status <bad> --json` errors on stderr with a clean stdout stream."""
    result = CliRunner().invoke(main, ["policy", "shadow", "status", "ghost-xyz", "--json"])

    assert result.exit_code == 1
    assert "ghost-xyz" in json.loads(result.stderr)["error"]
    # stdout is the results stream -- it must stay clean (no partial/invalid JSON, no error text).
    assert result.stdout == ""
