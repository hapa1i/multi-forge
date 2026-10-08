# Runtime-design partition checklist

Card: [Partition the Runtime Design](card.md). Branch: `docs/partition-runtime-design`, stacked on
[session partition PR #258](https://github.com/hapa1i/multi-forge/pull/258).

## Current focus

Closed on 2026-10-08 after the stack merged to `main`. `design_subprocesses.md` owns subprocess transport selection and
consumer-lane contracts; the entry point retains runtime lifecycle, model catalogs, configuration, and isolation.

## Execution

- [x] Activate the card on a separate branch and select §3.6.12 and §G as a cohesive owner.
- [x] Move complete sections and update inbound links plus Claude/Codex gather-context routing.
- [x] Verify lossless reconstruction after normalizing only rewritten links and formatting whitespace.
- [x] Record exact-content Opus 5 counts at or below 23,000 per partition.
- [x] Run Markdown, size/link, and working-tree/staged diff checks.
- [x] Commit and open the prerequisite PR; integrate the tested partitions into B1.

## Closeout

- [x] Verify merge/check results, record closeout, move to `done/`, and repoint links.

## Evidence

Original SHA-256: `62c1e409f980506b55686009ac8431b79abfa93808362eda944089f38960ac79`.

2026-10-07: lossless reconstruction passed after normalizing links and whitespace. Exact Opus 5 counts: runtime entry
point 16,864; subprocess contracts 8,286. Markdown size/link checks and diff checks pass; the link audit covers 641
sources.

2026-10-08 closeout: [PR #259](https://github.com/hapa1i/multi-forge/pull/259) merged into the session partition as
`d437efdd`; [#258](https://github.com/hapa1i/multi-forge/pull/258) then merged the stack to `main` as `56d4b8f5`. The
main tree matches tested head `2a3e7279`, with all five GitHub checks passing. The
[B1 closeout](../plan_file_supervision/checklist.md#merged-closeout) records the integrated verification.
