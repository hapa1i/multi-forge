"""The admitted native fork request, distinct from fresh and resume requests."""

from __future__ import annotations

import json
from dataclasses import dataclass

from forge.core.invoker.types import Attribution, HeadlessRequest
from forge.core.worker_controls import CODEX_WORKER_PROFILE


@dataclass(frozen=True)
class CodexUsageBaseline:
    """Source event token_count totals, never the post-compaction thread counter."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int

    def as_dict(self) -> dict[str, int | None]:
        return dict(input_tokens=self.input_tokens, output_tokens=self.output_tokens, cached_tokens=self.cached_tokens)


@dataclass
class CodexForkRequest(HeadlessRequest):
    usage_baseline: CodexUsageBaseline | None = None


def fork_usage_delta(baseline: CodexUsageBaseline | None, terminal: dict[str, int | None]) -> dict[str, int | None]:
    """Report unknown rather than charge inherited or incomparable counters."""
    unknown = dict.fromkeys(terminal)
    if baseline is None:
        return unknown
    before = baseline.as_dict()
    if any(type(value) is not int or value < 0 for value in (*before.values(), *terminal.values())):
        return unknown
    # The checks above narrow at runtime; explicit assertions keep arithmetic typed.
    delta: dict[str, int | None] = {}
    for name, value in terminal.items():
        previous = before[name]
        assert value is not None and previous is not None
        if value < previous:
            return unknown
        delta[name] = value - previous
    if (delta["cached_tokens"] or 0) > (delta["input_tokens"] or 0):
        return unknown
    return delta


def prepare_codex_fork_request(
    *,
    binary: str,
    source_id: str,
    prompt: str,
    env: dict[str, str],
    cwd: str,
    sqlite_home: str,
    schema_path: str,
    model: str,
    effort: str,
    auth_mode: str,
    deadline: float,
    lease_fd: int,
    baseline: CodexUsageBaseline | None,
    attribution: Attribution,
) -> CodexForkRequest:
    """Put isolation and auth controls on the fork leaf; deliver evidence on stdin."""
    if auth_mode not in {"subscription-only", "api"}:
        raise ValueError("Native Codex reviews require an explicit auth route")
    argv = [binary, "exec", "--json", "--sandbox", "read-only", "-C", cwd, "fork", "--ephemeral"]
    argv += ["--ignore-user-config", "--ignore-rules", "--output-schema", schema_path, "-m", model]
    for feature in ("hooks", "apps", "plugins"):
        argv += ["--disable", feature]
    for config in (
        f'cli_auth_credentials_store="{"file" if auth_mode == "subscription-only" else "ephemeral"}"',
        f'forced_login_method="{"chatgpt" if auth_mode == "subscription-only" else "api"}"',
        f"model_reasoning_effort={json.dumps(effort)}",
        f"sqlite_home={json.dumps(sqlite_home)}",
    ):
        argv += ["-c", config]
    CODEX_WORKER_PROFILE.apply(argv, env)
    argv += [source_id, "-"]
    return CodexForkRequest(
        argv=argv,
        prompt=prompt,
        env=env,
        cwd=cwd,
        model=model,
        provider="openai",
        label="supervisor",
        output_format=None,
        watchdog_deadline=deadline,
        pass_fds=(lease_fd,),
        cancel_before_kill=True,
        usage_baseline=baseline,
        attribution=attribution,
    )
