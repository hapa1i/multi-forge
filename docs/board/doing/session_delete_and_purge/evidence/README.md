# Session cleanup evidence

Two separately approved Claude 2.1.245 captures ran in fresh Docker containers with isolated homes, no host mounts, the
fixed acknowledgement workload, and no Codex invocation. Each requested and completed one subagent. The first reported
$0.01699045 and the second $0.0170009, totaling $0.03399135. Both observed the real process census refusing while Claude
was live and admitting after exit. Both containers were removed after export.

| Evidence                                                                                                                                                                                                                                                 | Result                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| [First execution](native-probe-20261020/execution.json), [native result](native-probe-20261020/container-evidence/native-result.json)                                                                                                                    | Workload completed; cleanup validation refused an uncharacterized `.meta.json` companion. |
| [Companion execution](native-companion-probe-20261020/execution.json), [native result](native-companion-probe-20261020/container-evidence/native-result.json), [export hashes](native-companion-probe-20261020/container-evidence/export-inventory.json) | Captured the exact parent JSONL, agent JSONL, and companion object for offline review.    |

The companion validator accepts exactly `agentType`, `description`, `toolUseId`, and integer `spawnDepth: 1`, in a
bounded object of at most 64 KiB. Its tool ID, agent type, and description must match one Agent request in the validated
parent transcript. The corresponding agent JSONL must also match the parent session UUID, launch CWD, CLI version,
sidechain identity, and agent filename. Unknown fields, deeper agents, legacy metadata locations, missing counterparts,
and mismatches refuse cleanup.

Both paid captures precede this validator implementation. They establish the observed file shape. The subsequent
[offline execution](offline-native-replay-20261020/execution.json) tested the implemented cleanup against those saved
bytes with networking disabled, no provider credentials, no host mounts, and zero native invocations.
[All 297 selected tests passed](offline-native-replay-20261020/offline-tests.txt), covering the three Docker lifecycle
cases plus hooks, rollover, content, orphan artifacts, and reviewer leases.

The [lifecycle assertions](offline-native-replay-20261020/container-evidence/replay-result.json) show that delete
preserved all three captured hashes and purge removed exactly the parent, agent, and metadata files. Relocated and
rewind copies were removed while their source and an unrelated sentinel remained intact. The evidence records the image
identity and [source hashes](offline-native-replay-20261020/source-sha256.json). The container was removed after export.

A final correction binds relative child-context paths to the child's Forge root, including when the same path exists in
its parent's root. The [subsequent offline check](offline-native-replay-20261020/child-context-regression.json) records
the updated source hashes and content/coordinator test result. This correction does not change native metadata
admission.

Provider copies, project memory documents, Git history, global telemetry, Claude history/file-history, native indexes,
uncharacterized companions, and copies outside the recorded native store remain outside supported removal or cause
explicit refusal when their ownership or dependencies cannot be established. A process census cannot stop an external
client from starting immediately after observation.

Codex support reuses the checked-in 0.162.1
[ancestry capture](../../../done/codex_fork_supervisor/evidence/ancestry.json) and
[provenance](../../../done/codex_fork_supervisor/evidence/provenance.json), captured against Forge source revision
`0aca9c7e6c7fecba63a1093674936aca4ac003ec` and native binary SHA-256
`74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. Its paginated history depends on the recorded parent
byte/ordinal reference, so a native descendant prevents parent purge. The QA pin alone does not admit Codex 0.149.1
destructive cleanup. No new Codex call was made for this card.
