# CLI mirror coverage

Static comparison against `f9faedd9` identifies 25 candidates: 17 proxy tests and 8 session tests. Remove 22 and retain
3 as real-process representatives. The card did not name the original detector's candidates; this inventory records the
reviewed set used for implementation.

The named unit twins cover every removed test's exit-status, message and filesystem assertions. The session empty-list,
start-success and default-direct twins assert their messages on `result.stdout`, preserving the removed subprocess
tests' stream checks instead of accepting merged `result.output`. Unit twins use `CliRunner`; the retained integration
tests below preserve command execution through the installed `forge` entry point. Runtime verification belongs in the
card checklist.

## Proxy candidates

The integration source is
[`test_proxy_commands_integration.py`](../../../../tests/integration/cli/test_proxy_commands_integration.py). Each row's
unit twin has the identical `Class::test_name` in
[`test_proxy_commands.py`](../../../../tests/src/cli/test_proxy_commands.py).

Retained process coverage keys:

- **P-show:** `TestProxyShow::test_show_displays_proxy_yaml`.
- **P-validate:** `TestProxyValidate::test_validate_success`.
- **P-set:** `TestProxySet::test_set_nested_field_with_dot_notation`, including persisted YAML and its shell argument.
- **P-delete:** `TestProxyDelete::test_delete_last_managed_proxy_stops_process_and_removes_ownership`, including
  observed SIGTERM and removal of both configuration and registry ownership. Shared-server and cancellation tests also
  remain.
- **P-create:** `TestProxyCreateNoStart::test_create_creates_proxy_file`; all `TestProxyCreateAndStart` tests remain.
- **P-list:** `TestProxyList::test_list_shows_entries` and `TestProxyCreateNoStart::test_create_then_list_shows_proxy`.

| Integration candidate and unit twin                                    | Decision | Retained process coverage |
| ---------------------------------------------------------------------- | -------- | ------------------------- |
| `TestProxyShow::test_show_not_found_error`                             | Remove   | P-show                    |
| `TestProxyValidate::test_validate_success`                             | Keep     | P-validate                |
| `TestProxyValidate::test_validate_invalid_yaml`                        | Remove   | P-validate                |
| `TestProxyValidate::test_validate_missing_required_field`              | Remove   | P-validate                |
| `TestProxyValidate::test_validate_not_found_error`                     | Remove   | P-validate                |
| `TestProxySet::test_set_simple_field`                                  | Remove   | P-set                     |
| `TestProxySet::test_set_nested_field_with_dot_notation`                | Keep     | P-set                     |
| `TestProxySet::test_set_invalid_format_error`                          | Remove   | P-set                     |
| `TestProxySet::test_set_not_found_error`                               | Remove   | P-set                     |
| `TestProxyDelete::test_delete_removes_proxy_and_registry`              | Remove   | P-delete                  |
| `TestProxyDelete::test_delete_not_found_error`                         | Remove   | P-delete                  |
| `TestProxyCreateNoStart::test_create_already_exists_error`             | Remove   | P-create                  |
| `TestProxyCreateNoStart::test_create_invalid_template_error`           | Remove   | P-create                  |
| `TestProxyCreateNoStart::test_create_with_custom_port`                 | Remove   | P-create                  |
| `TestProxyRegistryCorruption::test_list_with_invalid_json_registry`    | Remove   | P-list                    |
| `TestProxyRegistryCorruption::test_list_with_missing_version_registry` | Remove   | P-list                    |
| `TestProxyRegistryCorruption::test_list_with_wrong_version_registry`   | Remove   | P-list                    |

## Session candidates

The integration source is
[`test_session_commands_integration.py`](../../../../tests/integration/cli/test_session_commands_integration.py). Each
row's unit twin has the identical `Class::test_name` in its listed unit file:

- **List:** [`test_session_list_show.py`](../../../../tests/src/cli/test_session_list_show.py).
- **Start:** [`test_session_start_delete.py`](../../../../tests/src/cli/test_session_start_delete.py).
- **Resume:** [`test_session_resume.py`](../../../../tests/src/cli/test_session_resume.py).
- **Overrides:** [`test_session_overrides.py`](../../../../tests/src/cli/test_session_overrides.py).

Transferred stream assertions:

- `TestSessionList::test_list_empty_shows_message`: `No sessions found` must appear on stdout.
- `TestSessionStart::test_start_creates_session`: `Created session` and `new-session` must appear on stdout.
- `TestSessionStart::test_start_defaults_to_direct`: `Routing: direct` must appear on stdout.

Retained process coverage keys:

- **S-list:** `TestSessionList::test_list_shows_sessions` preserves human-readable output.
  `TestSessionResume::test_missing_worktree_remains_visible_and_resume_refuses_without_mutation` also exercises JSON.
- **S-start:** `TestSessionStart::test_start_invokes_claude`, `test_start_creates_manifest_file` and
  `test_start_with_direct_model_pins_claude_env` preserve launch, persistence and model-route coverage.
- **S-resume:** `TestSessionResume::test_resume_existing_session`, `test_resume_invokes_claude_as_new_session` and all
  transcript reconnection scenarios remain.
- **S-set:** `TestSessionSetOverride::test_set_updates_overrides` and
  `test_launch_runtime_parent_override_is_rejected_and_recoverable` cover successful writes, refusal and recovery.

| Integration candidate and unit twin                  | Unit file | Decision | Retained process coverage |
| ---------------------------------------------------- | --------- | -------- | ------------------------- |
| `TestSessionList::test_list_empty_shows_message`     | List      | Remove   | S-list                    |
| `TestSessionList::test_list_shows_sessions`          | List      | Keep     | S-list                    |
| `TestSessionStart::test_start_creates_session`       | Start     | Remove   | S-start                   |
| `TestSessionStart::test_start_defaults_to_direct`    | Start     | Remove   | S-start                   |
| `TestSessionStart::test_start_duplicate_fails`       | Start     | Remove   | S-start                   |
| `TestSessionResume::test_resume_nonexistent_fails`   | Resume    | Remove   | S-resume                  |
| `TestSessionSetOverride::test_set_invalid_key_fails` | Overrides | Remove   | S-set                     |
| `TestSessionSetOverride::test_set_no_session_fails`  | Overrides | Remove   | S-set                     |

The other lifecycle, process, help, corruption and recovery tests remain. The removal count is 15 proxy tests plus 7
session tests; none of the removed functions is parametrized.

## Shared release artifact

The session-scoped `release_wheel` fixture in [`docker/conftest.py`](../../../../tests/integration/docker/conftest.py)
supplies the exact same `WheelArtifact` to `test_qa_release_artifact.py`, `test_walkthrough_release_artifact.py` and
`test_worker_native_controls.py`. The walkthrough mounts that artifact's directory read-only. Both QA images remain
separate, preserving their distinct runtime labels and cleanup ownership. The independent synthetic and Forge builds in
[`test_runtime_build_constraints.py`](../../../../tests/integration/docker/test_runtime_build_constraints.py) remain.
