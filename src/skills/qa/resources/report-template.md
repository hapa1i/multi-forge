# Forge QA Report

| Field                      | Value                                                                      |
| -------------------------- | -------------------------------------------------------------------------- |
| **Date**                   | YYYY-MM-DD                                                                 |
| **Artifact Path**          | canonical host path to the one wheel                                       |
| **Wheel Filename**         | `multi_forge-X.Y.Z-py3-none-any.whl`                                       |
| **Wheel SHA-256**          | 64 lowercase hexadecimal characters                                        |
| **Artifact Mode**          | `prebuilt` (release-capable) or `development-build` (development-only)     |
| **Forge Version**          | X.Y.Z from wheel metadata, `forge --version`, and `forge.__version__`      |
| **Container**              | container name and immutable image identity                                |
| **Checklist Version**      | X.Y.Z from checklist header `<!-- version: ... -->`                        |
| **Runtime Track**          | `pinned` (blocking) or `latest` (non-blocking compatibility)               |
| **Claude Pin / Observed**  | matrix version / `claude --version` output                                 |
| **Codex Pin / Observed**   | matrix version / `codex --version` output                                  |
| **Codex Auth Mode**        | `api-key`, `explicit-file`, or `none`; never include credential material   |
| **Provider Profile**       | `openrouter` or `remote-litellm`                                           |
| **Evidence Selection**     | selected lanes plus category/range filters                                 |
| **Duration Seconds**       | wall time from artifact validation through final report save               |
| **Budget Review Required** | `true` when duration exceeds 2700 seconds, otherwise `false`               |
| **Duration Disposition**   | maintainer response when review is required, otherwise `not required`      |
| **Human Checkpoints**      | blocking planned / completed (maximum 12); selected total if extended      |
| **Paid Operations**        | blocking planned / observed (maximum 8); selected total if extended        |
| **Driver Orchestration**   | reported separately; excluded from subject-under-test paid-operation count |
| **Release Verdict**        | blocking pass/fail, development-only, or non-blocking compatibility result |
| **Debug Logging**          | enabled by default; artifacts copied when present                          |

## Summary

| Category            | Total | Pass  | Fail  | Skip  |
| ------------------- | ----- | ----- | ----- | ----- |
| Release Artifact    | 0     | 0     | 0     | 0     |
| Pre-Flight          | 0     | 0     | 0     | 0     |
| Extensions          | 0     | 0     | 0     | 0     |
| Auth                | 0     | 0     | 0     | 0     |
| Proxy               | 0     | 0     | 0     | 0     |
| Session             | 0     | 0     | 0     | 0     |
| Hooks               | 0     | 0     | 0     | 0     |
| Costs               | 0     | 0     | 0     | 0     |
| Status Line         | 0     | 0     | 0     | 0     |
| Direct Commands     | 0     | 0     | 0     | 0     |
| Session Resume      | 0     | 0     | 0     | 0     |
| Runtime Config      | 0     | 0     | 0     | 0     |
| Search              | 0     | 0     | 0     | 0     |
| Policy              | 0     | 0     | 0     | 0     |
| Workflow Runners    | 0     | 0     | 0     | 0     |
| Skills              | 0     | 0     | 0     | 0     |
| Memory Writer       | 0     | 0     | 0     | 0     |
| System Info         | 0     | 0     | 0     | 0     |
| Incremental Disable | 0     | 0     | 0     | 0     |
| Complete Removal    | 0     | 0     | 0     | 0     |
| Cleanup             | 0     | 0     | 0     | 0     |
| **TOTAL**           | **0** | **0** | **0** | **0** |

## Issues Found

| #   | Section | Severity        | Description                                   |
| --- | ------- | --------------- | --------------------------------------------- |
| 1   | X.Y     | high/medium/low | Brief description of what failed or was wrong |

If no issues: "No issues found."

## Infrastructure

- **Forge**: version, install method (pip/uv)
- **Docker**: available/unavailable (docker info output)
- **Artifact provenance**: pass/fail for CLI, import, metadata, and packaged-resource isolation
- **Runtime readiness**: static Claude/Codex availability and auth/enrollment evidence actually probed
- **Proxies**: count from `forge proxy list`, or "not tested"
- **Credentials**: auth status from hermetic FORGE_HOME, or "not tested"

## Evidence Gaps

- **Automated-suite owners**: referenced paths; never count these as commands executed by this run
- **Skipped prerequisites**: step ids and missing infrastructure
- **Non-blocking compatibility failures**: latest-track observations; never promote them into the pinned verdict
- **Duration disposition**: maintainer decision when `Budget Review Required` is `true`

## Artifacts

- **step-logs/**: raw command output per checklist step (copied from the mounted QA state dir)
- **artifact.json**: wheel, image, provider, and observed runtime identity
- **selection.json**: selected step ids, evidence lanes, and planned deterministic budgets
- **run-metrics.json**: selected results, actual counts, duration review state, scope, and verdict
- **checklist-report.json**: parser-owned assertion detail; unselected ids are not release gaps
- **forge-logs/final/**: final Forge debug logs copied from the container at artifact-save time
- **forge-logs-snapshots/**: pre-clean snapshots captured before any checklist step runs `forge logs clean --yes`
- **transcript.jsonl**: copied when the QA session exits (if the transcript claim token is satisfied)

## Notes

Observations from human checkpoint verifications, edge cases noticed, or anything that passed but looked suspicious.
