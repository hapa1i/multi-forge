# Real-runtime authority end-to-end validation

**Status**: Active (2026-08-22). **Branch**: `test/authority-real-runtime-e2e`.

**Relationship**: post-ship validation for [Artifact Authority Mode](../../done/artifact_authority_mode/card.md). This
card adds no authority behavior or new runtime contract; it closes the real-model test gap left by M1's hermetic seam
coverage.

## Problem

M1 verifies authority through Docker and CLI integration tests, but its runtime-wire tests pipe synthetic hook payloads
directly and its full launch-lifecycle test replaces Claude with an executable that exits zero. Those tests prove the
launcher, registration, handler, journal, and retention seams independently. They do not prove the complete external
chain in which a real runtime receives Forge's marker, a real model requests a mutating tool, the installed hook denies
that request, the artifact remains absent, and the same run records the denial.

Forge already has a real-Claude Docker boundary. Codex adds two constraints to that boundary:

- the image must carry the real Codex CLI version selected by the host test runner;
- hook trust is an identity property of the operator's `CODEX_HOME`, its config path, and exact registered command
  bytes. The Docker fixture may copy only the two non-secret trusted hashes into the same absolute config path, let
  Forge install the exact rows there, and authenticate with an ephemeral API-key file. It must never copy `auth.json` or
  mutate the host config.

Docker remains the isolation boundary for both runtimes' settings, hooks, transcripts, generated artifacts, and Forge
state.

## Goal

Add slow, credential-gated release tests that traverse Forge's production authority launch transaction and actual
runtime hook delivery:

1. A real Claude advisory launch in Docker requests a `Bash` mutation, receives the authority denial, leaves the
   sentinel absent, and records the correlated lifecycle plus `request_denied` event.
2. A real Claude producer launch in Docker performs the equivalent mutation, proving the installed catch-all row does
   not falsely deny a marker-free producer.
3. A real Codex advisory launch in Docker requests `apply_patch`, receives the authority denial, leaves the sentinel
   absent, and records same-run lifecycle/denial evidence.

## Test boundary

- The tests may constrain the real runtime into a non-interactive, one-turn tool loop, but they must not invoke the
  authority hook directly, construct a marker in test code, patch the authority guard, or fake runtime output.
- The Claude wrapper may add `--print`, a fixed prompt, `--output-format json`, and an allowed-tool restriction to the
  command Forge constructed. It must exec the real binary and preserve Forge's argv and environment.
- The Codex test may use a deterministic structured parent transcript instead of paying for transfer curation.
  Preflight, per-launch enrollment verification, marker injection, `codex exec`, hook dispatch, and journal writes
  remain real.
- A real model may recover conversationally after a denied request, so process success is not the denial oracle. The
  sentinel's absence and a correlated `request_denied` event are the authority assertions.
- Missing credentials, runtime installation, or Codex enrollment fail loudly under the repository's no-skip policy.

## Acceptance boundary

- [x] The Claude advisory test crosses `forge session start --authority advisory` into the real Dockerized Claude binary
  and observes an actual installed-hook denial without manually supplying `FORGE_AUTHORITY_MARKER`.
- [x] The advisory sentinel is absent and the journal orders `launch_preflight` and `run_started` before at least one
  same-run `request_denied`, followed by `run_ended`.
- [x] The Claude producer control crosses the same real launcher/runtime boundary, writes its sentinel, and records no
  `request_denied` event.
- [x] The Codex advisory test uses the real Dockerized `codex exec` and a path-faithful copy of the operator's
  non-secret enrollment hashes through the public session CLI; it leaves the sentinel absent and records same-run
  denial/lifecycle evidence.
- [x] Tests are marked `integration`, `slow`, and `docker_in`; no host auth/config bytes are mutated and `auth.json` is
  never copied.
- [x] Existing hermetic authority tests remain unchanged and passing.

## Non-goals

- Changing authority policy, marker shape, launch preflight, journal schema, or user-facing commands.
- Treating model prose as proof that a hook fired.
- Automating or bypassing the Codex trust ceremony.
- Making paid real-model tests part of credential-free unit CI.

## Risks

- Model tool selection can drift. Prompts and allowed-tool restrictions must make the requested action narrow, while
  assertions rely on filesystem and journal state rather than response wording.
- A denied model may retry with another covered tool. The test accepts one or more denial events and requires that no
  sentinel lands.
- Codex enrollment verification spends one extra real turn before the authority test turn, by the ratified M1 posture.
- The Codex identity clone is valid only when its original absolute `CODEX_HOME` and `FORGE_HOME` paths can be recreated
  inside Docker and both expected user-hook hashes exist; otherwise the test fails with enrollment guidance.
- Test cleanup must remove the temporary Claude PATH override and key/prompt files even when a launch fails.
