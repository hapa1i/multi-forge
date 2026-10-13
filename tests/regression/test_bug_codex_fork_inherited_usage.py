"""A copied compacted source must not be counted again as new reviewer usage."""

import json
import subprocess
import time

import pytest

from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.codex_fork import CodexForkRequest, CodexUsageBaseline
from forge.core.invoker.types import Attribution

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "terminal,expected",
    [
        ({"input_tokens": 974814, "cached_input_tokens": 604288, "output_tokens": 461}, (162211, 80896, 163)),
        ({"input_tokens": 800000, "cached_input_tokens": 604288, "output_tokens": 461}, (None, None, None)),
        ({"input_tokens": 974814.5, "cached_input_tokens": 604288, "output_tokens": 461}, (None, None, None)),
        ({"input_tokens": 974814, "output_tokens": 461}, (None, None, None)),
    ],
)
def test_inherited_terminal_counters_emit_one_verified_delta(monkeypatch, terminal, expected):
    emitted = []
    request = CodexForkRequest(
        argv=["codex", "exec", "fork", "source", "-"],
        prompt="review evidence",
        env={},
        watchdog_deadline=time.monotonic() + 30,
        run_identity=("review", "parent", "root"),
        usage_baseline=CodexUsageBaseline(812603, 298, 523392),
        attribution=Attribution(command="supervisor", operation=None),
    )
    stream = json.dumps({"type": "turn.completed", "usage": terminal})
    monkeypatch.setattr(
        "forge.core.reactive.watchdog.run_guarded", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stream, "")
    )
    monkeypatch.setattr("forge.core.usage.emit_codex_usage", lambda **kw: emitted.append(kw))
    result = CodexHeadlessInvoker().run(request)
    assert (result.input_tokens, result.cached_tokens, result.output_tokens) == expected
    assert len(emitted) == 1
    assert (emitted[0]["input_tokens"], emitted[0]["cached_tokens"], emitted[0]["output_tokens"]) == expected
    assert result.terminal_usage is not None and result.inherited_usage is not None
    assert result.inherited_usage["input_tokens"] == 812603
    assert not request.env  # Run-tree/session identity stays out of the native child.
