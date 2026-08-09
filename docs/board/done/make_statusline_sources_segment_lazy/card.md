# Make status-line sources segment-lazy

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: D018 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `done/` -- shipped in PR #154 (`c4f14037`) after implementation, verification, and independent review.

## Goal

Run proxy and session discovery only when the resolved status-line segment layout consumes those sources.

## Design Authority

- [`docs/design_appendix.md` §A.8](../../../design_appendix.md#a8-status-line-guidance-3611): configured segments select
  information from stdin, session state, registry state, and live proxy truth.
- [`statusline/context.py` lazy-source contract](../../../../src/forge/cli/statusline/context.py): expensive derivations
  run only when an enabled segment accesses them.

## Evidence

Rechecked on merged `main` at `8f030ef4` with `statusline.segments: [path, branch]`. The retained regression observed
the exact call sequence `proxy`, `session` before the segment registry, even though neither source can affect that
layout. In a proxied managed session those calls include live HTTP plus registry/index/manifest reads on every poll.

## Implementation Outcome

Every registered segment now declares its proxy/session source requirements. The status-line command resolves one
immutable render plan before source acquisition, acquires each requested shared source at most once, and renders from
the same plan. A `path`/`branch` layout skips both probes, while empty/default and unknown-only fallback layouts retain
both sources and their existing byte-compatible fail-open behavior.

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

## Verification

The retained D018 regression failed on `8f030ef4`, then passed with the exhaustive source-declaration and full-command
probe matrix. The branch recorded 494 focused status-line/runtime-config/regression tests, 14 targeted Docker
integration tests, 8,929 unit tests (one skip, 122 deselected), 696 marked regressions, wheel/sdist and
packaged-resource checks, and final pre-commit. Independent review found no design or standard issues; GitHub Tests,
Pre-commit, and CodeQL passed on the final head. D018 shipped in PR #154 (`c4f14037`).
