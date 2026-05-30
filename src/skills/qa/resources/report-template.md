# Forge QA Report

| Field                 | Value                                                   |
| --------------------- | ------------------------------------------------------- |
| **Date**              | YYYY-MM-DD                                              |
| **Forge Version**     | X.Y.Z (output of `forge --version`)                     |
| **Container**         | container name (from `start-container.sh`)              |
| **Checklist Version** | X.Y.Z (from checklist header `<!-- version: ... -->`)   |
| **Duration**          | HH:MM (from state file started_at to last_updated)      |
| **Debug Logging**     | Enabled by default in QA; artifacts copied when present |

## Summary

| Category              | Total | Pass  | Fail  | Skip  |
| --------------------- | ----- | ----- | ----- | ----- |
| Enable (New User)     | 0     | 0     | 0     | 0     |
| Pre-Flight            | 0     | 0     | 0     | 0     |
| Extensions            | 0     | 0     | 0     | 0     |
| Auth                  | 0     | 0     | 0     | 0     |
| Proxy                 | 0     | 0     | 0     | 0     |
| Session               | 0     | 0     | 0     | 0     |
| Hooks                 | 0     | 0     | 0     | 0     |
| Status Line           | 0     | 0     | 0     | 0     |
| Direct Commands       | 0     | 0     | 0     | 0     |
| Session Resume        | 0     | 0     | 0     | 0     |
| Runtime Config        | 0     | 0     | 0     | 0     |
| Search                | 0     | 0     | 0     | 0     |
| Policy                | 0     | 0     | 0     | 0     |
| Workflow Runners      | 0     | 0     | 0     | 0     |
| Skills                | 0     | 0     | 0     | 0     |
| Memory Writer         | 0     | 0     | 0     | 0     |
| System Info           | 0     | 0     | 0     | 0     |
| Disable (Incremental) | 0     | 0     | 0     | 0     |
| Uninstall (Complete)  | 0     | 0     | 0     | 0     |
| Cleanup               | 0     | 0     | 0     | 0     |
| **TOTAL**             | **0** | **0** | **0** | **0** |

## Issues Found

| #   | Section | Severity        | Description                                   |
| --- | ------- | --------------- | --------------------------------------------- |
| 1   | X.Y     | high/medium/low | Brief description of what failed or was wrong |

If no issues: "No issues found."

## Infrastructure

- **Forge**: version, install method (pip/uv)
- **Docker**: available/unavailable (docker info output)
- **Proxies**: count from `forge proxy list`, or "not tested"
- **Credentials**: auth status from hermetic FORGE_HOME, or "not tested"

## Artifacts

- **step-logs/**: raw command output per checklist step (copied from the mounted QA state dir)
- **forge-logs/final/**: final Forge debug logs copied from the container at artifact-save time
- **forge-logs-snapshots/**: pre-clean snapshots captured before any checklist step runs `forge logs --clean`
- **transcript.jsonl**: copied when the QA session exits (if the transcript claim token is satisfied)

## Notes

Observations from human checkpoint verifications, edge cases noticed, or anything that passed but looked suspicious.
