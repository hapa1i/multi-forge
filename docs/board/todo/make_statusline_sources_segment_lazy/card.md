# Make status-line sources segment-lazy

**Epic**: [`epic_cli_proxy_runtime_correctness`](../../doing/epic_cli_proxy_runtime_correctness/card.md).

**Finding**: D018 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 5 member, parked last in the child epic.

## Goal

Run proxy and session discovery only when the resolved status-line segment layout consumes those sources.

## Design Authority

- [`docs/design_appendix.md` §A.8](../../../design_appendix.md#a8-status-line-guidance-3611): configured segments select
  information from stdin, session state, registry state, and live proxy truth.
- [`statusline/context.py` lazy-source contract](../../../../src/forge/cli/statusline/context.py): expensive derivations
  run only when an enabled segment accesses them.

## Evidence

Rechecked on `3f3a3c6d` with `statusline.segments: [path, branch]`. A disposable characterization observed both
`detect_proxy()` and `discover_session()` run before the segment registry, even though neither source can affect that
layout. In a proxied managed session those calls include live HTTP plus registry/index/manifest reads on every poll.

## Expected Behavior

- `path`/`branch`-only rendering performs no proxy HTTP/registry read and no session index/manifest read.
- Proxy- and session-dependent segments still acquire their sources once per poll and share the resulting facts.
- The empty/default layout remains byte-compatible, including fail-open behavior for an unavailable source.

## Acceptance Criteria

- Add a marked D018 regression that fails when unrelated layouts invoke either source probe.
- Give segment dependencies one registry-owned declaration; test default, proxy-only, session-only, and mixed layouts.
- Benchmark or instrument the zero-source path, run focused status-line/config tests, targeted session/proxy
  integration, and `make pre-commit`.

## Compatibility and Exclusions

- Do not infer session identity from CWD or Claude's `session_id`; `FORGE_SESSION` remains authoritative.
- Do not alter segment order, formatting, palette/glyph behavior, source fallback semantics, or per-producer fail-open.
