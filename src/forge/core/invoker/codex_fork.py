"""The admitted native fork request, distinct from fresh and resume requests."""

from __future__ import annotations

import json
from dataclasses import dataclass

from forge.core.invoker.types import Attribution, HeadlessRequest
from forge.core.runtime.codex_usage import CodexUsageBaseline
from forge.core.worker_controls import CODEX_WORKER_PROFILE


@dataclass
class CodexContinuationRequest(HeadlessRequest):
    """A native continuation reports cumulative JSONL counters for the thread."""

    usage_baseline: CodexUsageBaseline | None = None


class CodexForkRequest(CodexContinuationRequest):
    """Native review fork with its separately admitted source prefix."""


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
